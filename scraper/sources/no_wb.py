"""
no-wb.org source adapter.

no-wb.org is a list of companies that don't use whiteboard interviews.
Each page lists 26 companies as <article class="company-card">.

Pagination: /page/2, /page/3, ... up to max_pages.

Each card has:
  - <a href="https://ats.example.com/...">  (the company's careers page)
  - <h3>Company Name</h3>
  - A "Remote" badge (if applicable)
  - A short description of the interview process
  - Location info

Since no-wb lists companies (not individual jobs), we treat each company
as a "job" entry whose ats_url points to the company's careers page.
The downstream pipeline then deep-scrapes that page using the GenericParser.
"""
from __future__ import annotations

import logging
import re
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..data_model import RawJob
from ..providers import detect_provider
from .base import SourceAdapter, register_adapter

log = logging.getLogger("scraper.sources.no_wb")


@register_adapter
class NoWbAdapter(SourceAdapter):
    name = "no_wb"

    def fetch_jobs(self) -> List[RawJob]:
        max_pages = int(self.cfg.options.get("max_pages", 4))
        all_jobs: List[RawJob] = []
        for page_num in range(1, max_pages + 1):
            if page_num == 1:
                url = self.cfg.url.rstrip("/") + "/"
            else:
                url = urljoin(self.cfg.url.rstrip("/") + "/", f"page/{page_num}")
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
        for article in soup.find_all("article"):
            try:
                job = self._parse_card(article)
                if job:
                    jobs.append(job)
            except Exception as e:
                log.debug("error parsing no-wb card: %s", e)
        return jobs

    def _parse_card(self, article):
        # First <a> with href is the careers page link
        apply_a = article.find("a", href=True)
        if not apply_a:
            return None
        apply_url = apply_a["href"]
        if not apply_url.startswith("http"):
            return None

        # Company name from <h3>
        h3 = article.find("h3")
        company = h3.get_text(strip=True) if h3 else ""

        # "Remote" badge
        is_remote = False
        for span in article.find_all("span"):
            if span.get_text(strip=True).lower() == "remote":
                is_remote = True
                break

        # Location and interview process description
        # The card structure: company | Remote badge | interview process | location
        full_text = article.get_text(" | ", strip=True)
        # Strip the company name and "Remote" from the text to get the rest
        rest = full_text.replace(company, "", 1).replace("Remote", "", 1).strip(" |").strip()
        # Try to identify location — usually a city, country at the end
        location = ""
        # Look for patterns like "City, Country"
        m = re.search(r"([A-Z][a-zA-Z\s]+,\s*[A-Z][a-zA-Z\s]+)$", rest)
        if m:
            location = m.group(1).strip()
        # If remote badge, prepend "Remote" to location
        if is_remote and location:
            location = f"Remote | {location}"
        elif is_remote:
            location = "Remote"

        # Description: the interview process text
        description = rest
        if location:
            description = rest[:rest.rfind(location)].strip(" |").strip()

        return RawJob(
            source=self.name,
            title=f"See open roles at {company}" if company else "Open roles",
            company=company,
            location=location,
            posted_date=None,  # no-wb doesn't show posting dates
            ats_url=apply_url,
            ats_provider=detect_provider(apply_url),
            description_hint=f"No whiteboard interview process. {description}",
        )
