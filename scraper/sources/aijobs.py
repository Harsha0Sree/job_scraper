"""
aijobs.net source adapter.

List page: https://aijobs.net/?location=remote (or just /)
Pagination: ?page=N (50 jobs/page)

Each job is an <li> with:
  - <a href="/job/<slug>/">Title</a>  (relative URL — needs prefixing)
  - Salary span (text-bg-success)
  - "Remote work" span (text-success) if remote
  - Seniority span (text-bg-warning)
  - Time-ago div (text-muted)

Detail page: https://aijobs.net/job/<slug>/
  - Has full description in the main content area
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

log = logging.getLogger("scraper.sources.aijobs")

_BASE = "https://aijobs.net"


@register_adapter
class AiJobsAdapter(SourceAdapter):
    name = "aijobs"

    def fetch_jobs(self) -> List[RawJob]:
        max_pages = int(self.cfg.options.get("max_pages", 2))
        all_jobs: List[RawJob] = []
        for page_num in range(1, max_pages + 1):
            sep = "&" if "?" in self.cfg.url else "?"
            url = f"{self.cfg.url}{sep}page={page_num}" if page_num > 1 else self.cfg.url
            log.info("[%s] fetching page %d: %s", self.name, page_num, url)
            r = self.fetcher.get(url, use_cache=True)
            if not r.ok:
                log.warning("[%s] page %d fetch failed: %s", self.name, page_num, r.error)
                continue
            jobs = self._parse(r.text)
            if not jobs:
                log.info("[%s] no more jobs on page %d, stopping", self.name, page_num)
                break
            all_jobs.extend(jobs)
        log.info("[%s] parsed %d jobs from %d pages", self.name, len(all_jobs), max_pages)
        return all_jobs

    def _parse(self, html: str) -> List[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: List[RawJob] = []
        for li in soup.find_all("li"):
            a = li.find("a", href=re.compile(r"^/job/"))
            if not a:
                continue
            try:
                job = self._parse_card(li, a)
                if job:
                    jobs.append(job)
            except Exception as e:
                log.debug("error parsing aijobs card: %s", e)
        return jobs

    def _parse_card(self, li, a):
        href = a["href"]
        ats_url = urljoin(_BASE, href)
        # Title: strip "Featured" / "Feat." badges
        title = a.get_text(" ", strip=True)
        title = re.sub(r"^(Featured|Feat\.)\s*", "", title).strip()

        # Salary
        salary = ""
        sal_span = li.find("span", class_=re.compile(r"text-bg-success"))
        if sal_span:
            sal_text = sal_span.get_text(strip=True)
            if "$" in sal_text or "€" in sal_text or "£" in sal_text or "K" in sal_text:
                salary = sal_text

        # Remote
        is_remote = False
        remote_text = ""
        for span in li.find_all("span", class_=re.compile(r"text-success")):
            t = span.get_text(strip=True)
            if "remote" in t.lower():
                is_remote = True
                remote_text = t
                break

        # Seniority
        sen = li.find("span", class_=re.compile(r"text-bg-warning"))
        seniority = sen.get_text(strip=True) if sen else ""

        # Time-ago
        time_div = li.find("div", class_=re.compile(r"text-muted"))
        time_text = time_div.get_text(strip=True) if time_div else ""
        posted_date = parse_posted_date(time_text) if time_text else None

        # Tags (skills)
        tags = []
        for span in li.find_all("span"):
            cls = " ".join(span.get("class", []))
            if "text-bg" not in cls and "text-success" not in cls and span.get_text(strip=True):
                t = span.get_text(strip=True)
                if t and len(t) < 50 and t not in (title, salary, seniority, time_text):
                    tags.append(t)

        # Location: aijobs has a right-side div with structure:
        #   <div class="text-end">
        #     <div>[Seniority badge] [Type badge] [Type badge]</div>
        #     <div>Location text <span class="text-bg-success">R</span></div>
        #     <div class="text-muted">9d ago</div>
        #   </div>
        # The SECOND <div> child is the location. We want just that.
        location = ""
        right_div = li.find("div", class_=re.compile(r"text-end"))
        if right_div:
            # Get the direct child divs
            child_divs = right_div.find_all("div", recursive=False)
            if len(child_divs) >= 2:
                # The second div is the location (first is seniority/type badges)
                loc_div = child_divs[1]
                loc_text = loc_div.get_text(" ", strip=True)
                # Remove the "R" remote marker
                loc_text = re.sub(r"\s+R\s*$", "", loc_text).strip()
                if loc_text:
                    location = loc_text
        if not location and is_remote:
            location = remote_text

        # Description hint
        desc_parts = []
        if seniority: desc_parts.append(f"Seniority: {seniority}")
        if salary: desc_parts.append(f"Salary: {salary}")
        if tags: desc_parts.append(f"Skills: {', '.join(tags[:8])}")
        description = " | ".join(desc_parts)

        return RawJob(
            source=self.name,
            title=title,
            company="",  # aijobs doesn't always show company on list page
            location=location,
            posted_date=posted_date,
            ats_url=ats_url,
            ats_provider="aijobs",  # we'll deep-scrape the aijobs detail page
            description_hint=description,
            seniority=seniority,
        )
