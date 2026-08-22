"""
Filters: location (remote-anywhere / remote-India / onsite-India) +
category (backend/AI engineering, title-focused) +
zero-experience detection.

A job is ACCEPTED only when ALL three filters pass:
  1. Location:   remote-from-anywhere OR remote-from-India OR onsite-in-India
  2. Category:   title contains a backend OR AI engineering keyword,
                 AND title doesn't contain an excluded keyword.
  3. Experience: title is not senior, description doesn't mention N+ years,
                 AND title/description contains an entry-level signal.

Every decision is logged with the specific signal matched, so the audit
trail in the Excel sheet shows exactly why each job was accepted/rejected.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List

from .config import FiltersConfig
from .data_model import RawJob, ScrapedJob

log = logging.getLogger("scraper.filters")


@dataclass
class FilterResult:
    accepted: bool
    reason: str
    location_type: str = ""       # "remote_anywhere", "remote_india", "onsite_india", ""
    is_location_match: bool = False
    is_category_match: bool = False
    category_signals: List[str] = field(default_factory=list)
    experience_signals: List[str] = field(default_factory=list)
    years_mentioned: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Location filter
#  Accepts: remote-anywhere OR remote-India OR onsite-India
# --------------------------------------------------------------------------- #

def detect_location(location_text: str, cfg: FiltersConfig) -> tuple[bool, str, str]:
    """
    Decide whether a job's location qualifies.
    Returns (is_match, location_type, reason).
    location_type is one of: "remote_anywhere", "remote_india", "onsite_india", ""
    """
    if not location_text:
        return False, "", "no location text"

    t = location_text.lower().strip()

    # 1. Remote-from-anywhere patterns — accept unconditionally
    for pat in cfg.location.remote_anywhere_patterns:
        if pat.lower() in t:
            return True, "remote_anywhere", f"remote-anywhere: '{pat}'"

    # 2. Remote-from-India patterns — accept
    for pat in cfg.location.remote_india_patterns:
        if pat.lower() in t:
            return True, "remote_india", f"remote-india: '{pat}'"

    # 3. Check if India is mentioned (city, state, or "india")
    # IMPORTANT: use word-boundary matching to avoid "indonesia" matching "india"
    def _has_india_location(text: str) -> tuple[bool, str]:
        for loc in cfg.location.india_locations:
            loc_l = loc.lower().strip()
            if not loc_l:
                continue
            # Use word-boundary regex to avoid substring false positives
            # e.g. "india" should NOT match "indonesia"
            try:
                if re.search(r"\b" + re.escape(loc_l) + r"\b", text):
                    return True, loc
            except re.error:
                # Fallback to substring if regex fails
                if loc_l in text:
                    return True, loc
        return False, ""

    is_india, matched_loc = _has_india_location(t)

    # 4. Restricted remotes (US/Europe/etc.) — REJECT
    #    Unless India is ALSO mentioned
    if not is_india:
        for pat in cfg.location.restricted_remote_patterns:
            if pat.lower() in t:
                return False, "", f"restricted-remote: '{pat}'"

    # 5. Has the word "remote"?
    has_remote_word = bool(re.search(r"\bremote\b", t)) or "wfh" in t or "work from home" in t

    # 6. If India is mentioned + "remote" → remote-India
    if is_india and has_remote_word:
        return True, "remote_india", f"remote-india (location: '{matched_loc}')"

    # 7. If India is mentioned (no "remote" word) → onsite-India
    if is_india:
        return True, "onsite_india", f"onsite-india (location: '{matched_loc}')"

    # 8. Bare "Remote" (no qualifier, no India) — REJECT in strict mode
    if has_remote_word:
        return False, "", "bare-remote (no anywhere/india qualifier)"

    # 9. Non-remote, non-India
    return False, "", "not remote, not india"


# --------------------------------------------------------------------------- #
#  Category filter (backend / AI engineering — title-focused)
# --------------------------------------------------------------------------- #

def detect_category(title: str, description: str, cfg: FiltersConfig) -> tuple[bool, list[str]]:
    """
    Return (is_match, list_of_matched_signals).
    A job matches if its TITLE contains any backend or AI keyword,
    AND its title doesn't contain an excluded keyword (frontend/mobile/etc.).

    Title-focused to avoid false positives (e.g. a frontend job whose
    description mentions "our backend API" should NOT match).
    """
    title_l = (title or "").lower()

    # Exclude by title first
    for kw in cfg.category.exclude_title_keywords:
        kw_l = kw.lower().strip()
        if not kw_l:
            continue
        if re.search(r"\b" + re.escape(kw_l) + r"\b", title_l):
            return False, [f"excluded:{kw}"]

    signals: list[str] = []
    for kw in cfg.category.backend_title_keywords:
        kw_l = kw.lower().strip()
        if not kw_l:
            continue
        if kw_l in title_l:
            signals.append(f"backend:{kw}")
    for kw in cfg.category.ai_title_keywords:
        kw_l = kw.lower().strip()
        if not kw_l:
            continue
        if kw_l in title_l:
            signals.append(f"ai:{kw}")

    return (len(signals) > 0, signals)


# --------------------------------------------------------------------------- #
#  Zero-experience detector
# --------------------------------------------------------------------------- #

def detect_zero_experience(
    title: str,
    description: str,
    seniority_text: str,
    cfg: FiltersConfig,
) -> tuple[bool, list[str], list[str]]:
    """
    Returns (accepted, signals, years_hits).

    `seniority_text` is an optional seniority tag from the ATS (e.g.
    "Entry level", "Mid-level", "Senior-level"). If present, it's used
    as a strong signal in both directions.
    """
    title_l = (title or "").lower()
    desc_l = (description or "").lower()
    combined = f"{title_l}\n{desc_l}"
    sen_l = (seniority_text or "").lower().strip()

    signals: list[str] = []
    years_hits: list[str] = []

    # 1. Senior title keywords -> auto-reject
    for kw in cfg.zero_experience.senior_keywords:
        kw_l = kw.lower().strip()
        if not kw_l:
            continue
        if re.search(r"\b" + re.escape(kw_l) + r"\b", title_l):
            return False, [f"senior-title:{kw}"], years_hits

    # 2. Seniority level from ATS tag -> reject if senior/mid
    if sen_l:
        for lvl in cfg.zero_experience.seniority_levels_rejected:
            if lvl.lower() in sen_l:
                return False, [f"seniority:{lvl}"], years_hits

    # 3. Min-years patterns -> reject if captured number >= threshold
    # BUT: skip matches that are:
    #   - Part of a "0-N" range (entry-level signal)
    #   - In a "Do you have" question (application form, not a requirement)
    #   - In a self-assessment checkbox context
    def _is_part_of_zero_range(text: str, match_start: int) -> bool:
        """Check if the digits at match_start are preceded by '0-' or '0 to'."""
        before = text[max(0, match_start - 10):match_start]
        return bool(re.search(r"\b0\s*[-–—to]{1,3}\s*$|\b0\s+to\s*$", before))

    def _is_in_form_context(text: str, match_start: int, match_end: int) -> bool:
        """Check if the match is in an application form question."""
        # Look at 60 chars before the match
        before = text[max(0, match_start - 60):match_start]
        # Look at 30 chars after
        after = text[match_end:min(len(text), match_end + 30)]
        # Form-like patterns: "Do you have", "min ", "Select...", "*Select"
        form_patterns = [
            r"do\s+you\s+have",
            r"have\s+(?:a\s+)?min",
            r"\*\s*select",
            r"select\.\.\.",
            r"are\s+you\s+\d+\+",
            r"years\s+of\s+age",
        ]
        for pat in form_patterns:
            if re.search(pat, before, re.IGNORECASE):
                return True
        # Also skip if followed by "*Select" (form dropdown)
        if re.search(r"^\s*\*\s*select", after, re.IGNORECASE):
            return True
        return False

    for pat in cfg.zero_experience.min_years_patterns:
        try:
            for m in re.finditer(pat, combined, re.IGNORECASE):
                grp = m.group(1) if m.groups() else None
                if grp is None:
                    continue
                try:
                    n = int(grp)
                except ValueError:
                    continue
                # Skip if this is part of a "0-N" range (entry-level)
                if _is_part_of_zero_range(combined, m.start()):
                    continue
                # Skip if this is in a form/question context
                if _is_in_form_context(combined, m.start(), m.end()):
                    continue
                years_hits.append(f"{m.group(0)}")
                if n == 0:
                    continue
                if n >= cfg.zero_experience.min_years_threshold:
                    return False, signals, years_hits
        except re.error as e:
            log.warning("invalid years regex %r: %s", pat, e)

    # 4. Entry-level signals -> accept if at least one matches
    for sig in cfg.zero_experience.entry_level_signals:
        sig_l = sig.lower().strip()
        if not sig_l:
            continue
        if sig_l in combined:
            signals.append(f"signal:{sig}")

    # 5. Entry-level seniority tag -> accept
    if sen_l:
        for lvl in cfg.zero_experience.entry_level_seniority_levels:
            if lvl.lower() in sen_l:
                signals.append(f"seniority:{lvl}")

    if signals:
        return True, signals, years_hits

    # 6. Permissive mode: accept if no years-mention AND no senior signal
    if cfg.zero_experience.include_no_mention and not years_hits:
        return True, ["permissive:no_mention"], years_hits

    return False, [], years_hits


# --------------------------------------------------------------------------- #
#  Combined filter
# --------------------------------------------------------------------------- #

def apply_filters(
    raw: RawJob,
    title: str,
    description: str,
    location: str,
    cfg: FiltersConfig,
    seniority_text: str = "",
) -> FilterResult:
    """Apply all three filters to a fetched job."""
    final_title = title or raw.title
    final_desc = description or raw.description_hint
    final_loc = location or raw.location

    # 1. Location filter first (cheapest, most selective)
    loc_ok, loc_type, loc_reason = detect_location(final_loc, cfg)
    if not loc_ok:
        return FilterResult(
            accepted=False,
            reason=f"location: {loc_reason}",
            location_type="",
            is_location_match=False,
        )

    # 2. Category filter (title-focused)
    cat_ok, cat_signals = detect_category(final_title, final_desc, cfg)
    if not cat_ok:
        reason = cat_signals[0] if cat_signals else "no backend/AI title keyword"
        return FilterResult(
            accepted=False,
            reason=f"category: {reason}",
            location_type=loc_type,
            is_location_match=True,
            is_category_match=False,
        )

    # 3. Zero-experience filter
    exp_ok, exp_signals, years_hits = detect_zero_experience(
        final_title, final_desc, seniority_text, cfg
    )
    if not exp_ok:
        reason = exp_signals[0] if exp_signals else "no entry-level signal"
        if years_hits:
            reason = f"requires {years_hits[0]}"
        return FilterResult(
            accepted=False,
            reason=f"experience: {reason}",
            location_type=loc_type,
            is_location_match=True,
            is_category_match=True,
            category_signals=cat_signals,
            years_mentioned=years_hits,
        )

    # All three pass
    return FilterResult(
        accepted=True,
        reason=f"all filters passed (loc={loc_type})",
        location_type=loc_type,
        is_location_match=True,
        is_category_match=True,
        category_signals=cat_signals,
        experience_signals=exp_signals,
        years_mentioned=years_hits,
    )
