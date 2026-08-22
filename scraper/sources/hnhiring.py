"""
hnhiring.com source adapter.

The site is an index of Hacker News "Who is Hiring?" monthly posts.
Each job is a <li class="job"> with the format:
    <div class="user"><a>HN username</a> <span>2026-07-15</span></div>
    <div class="body">
        Title | Location | Type | Salary
        <p>Description paragraph 1</p>
        <p>Description paragraph 2</p>
        ...
        <p>contact email</p>
    </div>

Each job has an optional external apply link (in the description) which we
extract; if none is present, we link to the HN comment page.
"""
from __future__ import annotations

import logging
import re
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..data_model import RawJob
from ..utils import parse_posted_date
from .base import SourceAdapter, register_adapter

log = logging.getLogger("scraper.sources.hnhiring")

# Apply URL patterns we recognise inside the job body text
_APPLY_URL_RE = re.compile(
    r"(https?://[^\s<>\"']+)",
    re.IGNORECASE,
)
# Hosts we want to deep-scrape (ATS providers)
_DEEP_SCRAPE_HOSTS = (
    "greenhouse.io", "ashbyhq.com", "lever.co", "workable.com",
    "smartrecruiters.com",
)


@register_adapter
class HnHiringAdapter(SourceAdapter):
    name = "hnhiring"

    def fetch_jobs(self) -> List[RawJob]:
        url = self.cfg.url
        log.info("[%s] fetching %s", self.name, url)
        r = self.fetcher.get(url, use_cache=False)
        if not r.ok:
            log.error("[%s] fetch failed: %s (status=%s)", self.name, r.error, r.status)
            return []
        jobs = self._parse(r.text, base_url=url)
        log.info("[%s] parsed %d jobs", self.name, len(jobs))
        return jobs

    def _parse(self, html: str, base_url: str) -> List[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: List[RawJob] = []
        for li in soup.find_all("li", class_=re.compile(r"\bjob\b")):
            try:
                job = self._parse_card(li, base_url)
                if job:
                    jobs.append(job)
            except Exception as e:
                log.debug("error parsing hnhiring card: %s", e)
        return jobs

    def _parse_card(self, li, base_url: str):
        # Date from the .user span
        user_div = li.find("div", class_=re.compile(r"\buser\b"))
        posted_date = None
        if user_div:
            date_span = user_div.find("span")
            if date_span:
                posted_date = parse_posted_date(date_span.get_text(strip=True))

        body = li.find("div", class_=re.compile(r"\bbody\b"))
        if not body:
            return None

        # First text node is "Title | Location | Type | Salary"
        # Find the first direct text child (not inside a <p>)
        first_line = ""
        for child in body.children:
            if isinstance(child, str) and child.strip():
                first_line = child.strip()
                break
            if hasattr(child, "name") and child.name != "p":
                txt = child.get_text(strip=True)
                if txt:
                    first_line = txt
                    break

        if not first_line:
            return None

        # Parse: Title | Location | Type | Salary
        # Split on " | " but title may contain "|"
        parts = [p.strip() for p in first_line.split("|")]
        if not parts:
            return None

        title = parts[0].strip()
        location = ""
        salary = ""
        for part in parts[1:]:
            pl = part.lower()
            if "remote" in pl or any(c.isalpha() and c.isupper() for c in part[:1]):
                if not location:
                    location = part
            elif "$" in part or "€" in part or "£" in part or "k" in pl:
                salary = part

        # Description: all <p> tags joined
        desc_paras = []
        for p in body.find_all("p"):
            t = p.get_text(strip=True)
            if t:
                desc_paras.append(t)
        description = "\n".join(desc_paras)

        # Find an apply URL — prefer ATS links in the description
        apply_url = ""
        ats_provider = "generic"
        # Look in <a> tags inside body
        for a in body.find_all("a", href=True):
            href = a["href"]
            if any(h in href for h in _DEEP_SCRAPE_HOSTS):
                apply_url = href
                ats_provider = _detect_provider(href)
                break
        # Fallback: scan description text for any URL
        if not apply_url:
            m = _APPLY_URL_RE.search(description)
            if m:
                candidate = m.group(1).rstrip(".,);]")
                if any(h in candidate for h in _DEEP_SCRAPE_HOSTS):
                    apply_url = candidate
                    ats_provider = _detect_provider(candidate)

        # If no ATS apply URL, SKIP this job — we can't deep-scrape a useful
        # description from the HN comment page, and hammering news.ycombinator.com
        # with 429s wastes time. The listing text already has enough to filter on.
        if not apply_url:
            # Use the description hint as the ats_url placeholder so the job
            # still gets filtered by the listing text. Mark provider as "hn_text".
            return RawJob(
                source=self.name,
                title=title,
                company="",
                location=location,
                posted_date=posted_date,
                ats_url=f"hnhiring://text/{hash(title) & 0xFFFFFFFF:08x}",
                ats_provider="hn_text",
                description_hint=description,
            )

        return RawJob(
            source=self.name,
            title=title,
            company="",  # hnhiring doesn't separate company from title clearly
            location=location,
            posted_date=posted_date,
            ats_url=apply_url,
            ats_provider=ats_provider,
            description_hint=description,
        )


def _detect_provider(url: str) -> str:
    u = url.lower()
    if "greenhouse.io" in u: return "greenhouse"
    if "ashbyhq.com" in u: return "ashby"
    if "lever.co" in u: return "lever"
    if "workable.com" in u: return "workable"
    if "smartrecruiters.com" in u: return "smartrecruiters"
    return "generic"
