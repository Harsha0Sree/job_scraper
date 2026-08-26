"""
Closed feedback loop: your job feedback becomes durable learned rules.

Flow:
  1. You record feedback (CLI or by editing data/feedback.yaml):
       uv run python -m scraper.cli feedback <url> --violated category \\
           --comment 'this is really a "growth marketing" role'
  2. process_feedback() runs automatically at the start of every scrape run
     (and on demand). For each new entry it analyses the stored job record
     and generalizes conservatively into data/learned_rules.yaml:

       - the exact job is suppressed (always)
       - the company is banned (always — you would not apply there again)
       - experience violations: HOW did it slip through? "3 yrs" learned as
         a years-regex variant; word numbers ("three years") learned as a
         banned phrase; seniority tokens in titles ("Sr.") learned
       - category violations: quoted phrases from your comment are banned
         instantly; distinctive title tokens are banned after 2+ offences
         (core terms like "engineer"/"data" can never be banned)
       - location violations: that exact location string is banned

  Every rule carries provenance (which job taught it, when, which constraint,
  your comment) so rules stay auditable and deletable.

Enforcement lives in LearnedRules.check(), called from the evaluation seam;
suppressed jobs die with a `feedback:` reason visible in logs and sheets.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

from .state import StateManager
from .utils import job_id, now_iso

log = logging.getLogger("scraper.feedback")

DEFAULT_FEEDBACK_PATH = "data/feedback.yaml"
DEFAULT_RULES_PATH = "data/learned_rules.yaml"
PROCESSED_PATH = "data/.feedback_processed.json"

# Tokens so central to the category that feedback must never ban them.
_PROTECTED_TITLE_TERMS = {
    "engineer", "engineering", "backend", "software", "developer",
    "development", "intern", "internship", "junior", "graduate", "grad",
    "trainee", "apprentice", "fresher", "freshers", "entry", "level",
    "associate", "ai", "ml", "data", "machine", "learning", "python",
    "fullstack", "platform", "devops", "sre", "site", "reliability",
    "cloud", "infrastructure", "technology", "technical", "product",
}
# Roman-numeral / abbreviation seniority markers worth learning on sight.
_SENIORITY_TOKENS = {"sr", "sr.", "jr", "ii", "iii", "iv", "head", "chief"}

_WORD_NUMBERS = ("one", "two", "three", "four", "five", "six", "seven",
                 "eight", "nine", "ten")
_YEARS_SLIP_RE = re.compile(
    r"\b(?:(?P<word>" + "|".join(_WORD_NUMBERS) + ")|(?P<num>\d{1,2}))"
    r"\s*\+?\s*(?:to|-|–|—)?\s*(?:\d{1,2})?\s*(?P<unit>years?|yrs?)\b",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r'"([^"]{3,80})"|\'([^\']{3,80})\'')
_TOKEN_RE = re.compile(r"[a-z]{4,}")

_LEGAL_SUFFIXES = (
    "incorporated", "corporation", "company", "limited", "labs", "inc",
    "llc", "ltd", "gmbh", "corp", "co", "pvt", "pte", "plc",
)


def normalize_company(name: str) -> str:
    """Canonical company key: lowercase, punctuation-free, suffix-stripped."""
    n = re.sub(r"[^\w\s]", " ", (name or "").lower())
    n = re.sub(r"\s+", " ", n).strip()
    while True:
        parts = n.rsplit(" ", 1)
        if len(parts) == 2 and parts[1] in _LEGAL_SUFFIXES:
            n = parts[0].strip()
            continue
        break
    return n


def _entry_hash(entry: dict) -> str:
    canonical = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
#  Feedback entries
# --------------------------------------------------------------------------- #

@dataclass
class FeedbackEntry:
    url: str
    action: str = "reject"          # reject | applied
    violated: List[str] = field(default_factory=list)  # location/category/experience
    comment: str = ""

    @classmethod
    def from_dict(cls, raw) -> "FeedbackEntry":
        return cls(
            url=str(raw.get("url") or "").strip(),
            action=str(raw.get("action") or "reject").strip().lower(),
            violated=[str(v).lower() for v in (raw.get("violated") or [])],
            comment=str(raw.get("comment") or ""),
        )


def append_entry(url: str, action: str = "reject",
                 violated: Optional[List[str]] = None, comment: str = "",
                 path: Optional[Path] = None) -> None:
    path = Path(path) if path else _default_path(DEFAULT_FEEDBACK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    if path.exists():
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    entries.append({
        "url": url,
        "action": action,
        "violated": list(violated or []),
        "comment": comment,
        "recorded_at": now_iso(),
    })
    path.write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def load_entries(path: Optional[Path] = None) -> List[FeedbackEntry]:
    path = Path(path) if path else _default_path(DEFAULT_FEEDBACK_PATH)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [FeedbackEntry.from_dict(e) for e in raw]


def _default_path(rel: str) -> Path:
    from .config import load_config
    return load_config().project_root / rel


# --------------------------------------------------------------------------- #
#  Learned rules
# --------------------------------------------------------------------------- #

@dataclass
class LearnedRules:
    banned_job_ids: Set[str] = field(default_factory=set)
    banned_companies: Set[str] = field(default_factory=set)   # normalized keys
    banned_title_keywords: List[str] = field(default_factory=list)  # word-boundary
    banned_phrases: List[str] = field(default_factory=list)   # substring, lowercased
    banned_locations: List[str] = field(default_factory=list)  # substring, lowercased
    banned_years_regexes: List[str] = field(default_factory=list)
    provenance: Dict[str, dict] = field(default_factory=dict)
    title_token_offences: Dict[str, int] = field(default_factory=dict)

    # ---- persistence ------------------------------------------------------ #
    @classmethod
    def load(cls, path: Path) -> "LearnedRules":
        path = Path(path)
        if not path.exists():
            return cls()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            banned_job_ids=set(raw.get("banned_job_ids") or []),
            banned_companies=set(raw.get("banned_companies") or []),
            banned_title_keywords=list(raw.get("banned_title_keywords") or []),
            banned_phrases=list(raw.get("banned_phrases") or []),
            banned_locations=list(raw.get("banned_locations") or []),
            banned_years_regexes=list(raw.get("banned_years_regexes") or []),
            provenance=dict(raw.get("provenance") or {}),
            title_token_offences=dict(raw.get("title_token_offences") or {}),
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": now_iso(),
            "banned_job_ids": sorted(self.banned_job_ids),
            "banned_companies": sorted(self.banned_companies),
            "banned_title_keywords": self.banned_title_keywords,
            "banned_phrases": self.banned_phrases,
            "banned_locations": self.banned_locations,
            "banned_years_regexes": self.banned_years_regexes,
            "title_token_offences": self.title_token_offences,
            "provenance": self.provenance,
        }
        path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")

    def _remember(self, kind: str, value: str, entry: FeedbackEntry,
                  job_url: str) -> None:
        self.provenance.setdefault(f"{kind}:{value}", {
            "from_url": job_url,
            "constraint": ",".join(entry.violated) or entry.action,
            "at": now_iso(),
            "comment": entry.comment,
        })

    def _learn(self, kind: str, value, entry: FeedbackEntry, job_url: str) -> bool:
        """Add a rule value if new. Returns True when newly learned."""
        buckets = {
            "job": self.banned_job_ids,
            "company": self.banned_companies,
        }
        if kind in buckets:
            added = value not in buckets[kind]
            buckets[kind].add(value)
        else:
            listing = {
                "title_keyword": self.banned_title_keywords,
                "phrase": self.banned_phrases,
                "location": self.banned_locations,
                "years_regex": self.banned_years_regexes,
            }[kind]
            added = value not in listing
            if added:
                listing.append(value)
        if added:
            self._remember(kind, str(value), entry, job_url)
        return added

    # ---- enforcement ------------------------------------------------------ #
    def check(self, jid: str, title: str, company: str, location: str,
              description: str) -> Optional[str]:
        """Return a 'feedback: ...' suppression reason, or None."""
        if jid and jid in self.banned_job_ids:
            return "feedback: job was marked rejected via feedback"
        if company and normalize_company(company) in self.banned_companies:
            return f"feedback: company '{company}' was banned via feedback"
        combined = f"{title or ''}\n{description or ''}".lower()
        for pattern in self.banned_years_regexes:
            try:
                m = re.search(pattern, combined, re.IGNORECASE)
            except re.error:
                continue
            if m:
                return (f"feedback: years requirement '{m.group(0)}' matches "
                        f"learned pattern")
        for phrase in self.banned_phrases:
            if phrase.lower() in combined:
                return f"feedback: phrase '{phrase}' was banned via feedback"
        title_l = (title or "").lower()
        for kw in self.banned_title_keywords:
            if re.search(r"\b" + re.escape(kw.lower()) + r"\b", title_l):
                return f"feedback: title contains '{kw}' banned via feedback"
        loc_l = (location or "").lower()
        for loc in self.banned_locations:
            if loc in loc_l:
                return f"feedback: location '{loc}' was banned via feedback"
        return None


# --------------------------------------------------------------------------- #
#  Processing
# --------------------------------------------------------------------------- #

@dataclass
class FeedbackReport:
    processed: int = 0
    skipped: int = 0
    applied_marked: List[str] = field(default_factory=list)
    rules_learned: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)   # urls with no record


def process_feedback(state: StateManager,
                     feedback_path: Optional[Path] = None,
                     rules_path: Optional[Path] = None,
                     processed_path: Optional[Path] = None,
                     senior_keywords: Optional[List[str]] = None,
                     ai_keywords: Optional[List[str]] = None) -> FeedbackReport:
    """Consume new feedback entries into learned rules + applied state."""
    feedback_path = Path(feedback_path) if feedback_path else _default_path(DEFAULT_FEEDBACK_PATH)
    rules_path = Path(rules_path) if rules_path else _default_path(DEFAULT_RULES_PATH)
    processed_path = Path(processed_path) if processed_path \
        else state.path.parent / ".feedback_processed.json"

    done: Set[str] = set()
    if processed_path.exists():
        try:
            done = set(json.loads(processed_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            done = set()

    rules = LearnedRules.load(rules_path)
    known_senior = {k.lower() for k in (senior_keywords or [])}
    known_ai = {k.lower() for k in (ai_keywords or [])}

    report = FeedbackReport()
    raw_entries = []
    if feedback_path.exists():
        raw_entries = yaml.safe_load(feedback_path.read_text(encoding="utf-8")) or []

    for raw in raw_entries:
        h = _entry_hash(raw)
        if h in done:
            report.skipped += 1
            continue
        entry = FeedbackEntry.from_dict(raw)
        if not entry.url:
            report.skipped += 1
            continue
        jid = job_id(entry.url)
        record = state.job_record(jid) or {}

        if entry.action == "applied":
            if state.mark_applied(jid, entry.url, note=entry.comment):
                report.applied_marked.append(entry.url)
            done.add(h)
            report.processed += 1
            continue

        # ---- reject: generalize ------------------------------------------ #
        # Quoted phrases from your comment are honoured even without a
        # stored record — explicit quotes need no context.
        _learn_quoted_phrases(rules, entry, entry.url, report)

        if not record:
            report.unresolved.append(entry.url)
            # Still suppress the exact job so it never resurfaces.
            if rules._learn("job", jid, entry, entry.url):
                report.rules_learned.append(f"job:{jid}")
            done.add(h)
            report.processed += 1
            continue

        if rules._learn("job", jid, entry, entry.url):
            report.rules_learned.append(f"job:{jid}")
        company = str(record.get("company") or "")
        if company and rules._learn("company", normalize_company(company),
                                    entry, entry.url):
            report.rules_learned.append(f"company:{normalize_company(company)}")

        title = str(record.get("title") or "")
        desc = str(record.get("description_preview") or "")
        text = f"{title}\n{desc}".lower()

        if "experience" in entry.violated:
            _learn_experience_slips(rules, entry, entry.url, text, title,
                                    known_senior, report)
        if "category" in entry.violated:
            _learn_category(rules, entry, entry.url, title, entry.comment,
                            known_ai, report)
        if "location" in entry.violated:
            loc = str(record.get("location") or "").strip().lower()
            if len(loc) >= 4 and rules._learn("location", loc, entry, entry.url):
                report.rules_learned.append(f"location:{loc}")

        done.add(h)
        report.processed += 1

    rules.save(rules_path)
    state.save()
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    processed_path.write_text(json.dumps(sorted(done)), encoding="utf-8")
    if report.processed:
        log.info("feedback processed: %d new (%d rules), %d already handled",
                 report.processed, len(report.rules_learned), report.skipped)
    return report


def _learn_experience_slips(rules: LearnedRules, entry: FeedbackEntry,
                            job_url: str, text: str, title: str,
                            known_senior: Set[str], report: FeedbackReport) -> None:
    """How did this too-experienced job evade the years/seniority checks?"""
    seen_units = set()
    for m in _YEARS_SLIP_RE.finditer(text):
        unit = m.group("unit").lower()
        seen_units.add(unit)
        if unit.startswith("yr") and rules._learn(
                "years_regex", r"(\d+)\s*yrs?\b", entry, job_url):
            report.rules_learned.append("years_regex:yrs")
        if m.group("word"):
            phrase = m.group(0).strip().lower()
            if rules._learn("phrase", phrase, entry, job_url):
                report.rules_learned.append(f"phrase:{phrase}")
    # Seniority abbreviations in the title that the config does not know.
    for token in _SENIORITY_TOKENS:
        if token in known_senior:
            continue
        if re.search(r"\b" + re.escape(token) + r"\b", title.lower()):
            if rules._learn("title_keyword", token, entry, job_url):
                report.rules_learned.append(f"title_keyword:{token}")


def _learn_quoted_phrases(rules: LearnedRules, entry: FeedbackEntry,
                          job_url: str, report: FeedbackReport) -> None:
    for m in _QUOTED_RE.findall(entry.comment or ""):
        phrase = next((g for g in m if g), None)
        if phrase and rules._learn("phrase", phrase.strip().lower(), entry, job_url):
            report.rules_learned.append(f"phrase:{phrase.strip().lower()}")


def _learn_category(rules: LearnedRules, entry: FeedbackEntry, job_url: str,
                    title: str, comment: str, known_ai: Set[str],
                    report: FeedbackReport) -> None:
    """Quoted phrases act immediately; distinctive tokens need 2 offences."""
    _learn_quoted_phrases(rules, entry, job_url, report)

    protected = _PROTECTED_TITLE_TERMS | {k.lower() for k in known_ai}
    for token in set(_TOKEN_RE.findall(title.lower())):
        if token in protected:
            continue
        key = token
        count = rules.title_token_offences.get(key, 0) + 1
        rules.title_token_offences[key] = count
        if count >= 2 and rules._learn("title_keyword", token, entry, job_url):
            report.rules_learned.append(f"title_keyword:{token}")
