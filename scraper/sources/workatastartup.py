"""workatastartup.com source adapter.

WAS uses Rails + React. The page loads data via a `data-page` attribute
on a div, containing HTML-entity-encoded JSON with a `props.jobs` array.

Each job has: id, title, jobType, location, roleType, salary, companyName,
companySlug, companyBatch, companyOneLiner, applyUrl.

The applyUrl requires login, so we use the public job detail page
https://www.workatastartup.com/jobs/<id> as the ats_url for deep-scraping.

Pagination: ?page=N (30 jobs/page)
"""
from __future__ import annotations

import html
import json
import logging
import re
from typing import List
from urllib.parse import urlencode, urlparse, parse_qsl

from bs4 import BeautifulSoup

from ..data_model import RawJob
from .base import SourceAdapter, register_adapter

log = logging.getLogger("scraper.sources.workatastartup")

_BASE = "https://www.workatastartup.com"


@register_adapter
class WorkAtAStartupAdapter(SourceAdapter):
    name = "workatastartup"

    def fetch_jobs(self) -> List[RawJob]:
        max_pages = int(self.cfg.options.get("max_pages", 2))
        all_jobs: List[RawJob] = []
        for page_num in range(1, max_pages + 1):
            # Append page=N to the query string
            parsed = urlparse(self.cfg.url)
            qs = dict(parse_qsl(parsed.query))
            qs["page"] = str(page_num)
            url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode(qs)}"
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

    def _parse(self, html_text: str) -> List[RawJob]:
        # Extract the data-page attribute (entity-encoded JSON)
        m = re.search(r'data-page="([^"]+)"', html_text)
        if not m:
            log.warning("[%s] no data-page attribute found", self.name)
            return []
        try:
            data = json.loads(html.unescape(m.group(1)))
        except json.JSONDecodeError as e:
            log.error("[%s] data-page JSON parse failed: %s", self.name, e)
            return []
        jobs_data = data.get("props", {}).get("jobs", []) or []
        jobs: List[RawJob] = []
        for j in jobs_data:
            try:
                job = self._parse_job(j)
                if job:
                    jobs.append(job)
            except Exception as e:
                log.debug("error parsing WAS job: %s", e)
        return jobs

    def _parse_job(self, j: dict) -> RawJob:
        job_id_num = j.get("id")
        if not job_id_num:
            return None
        # Use the public detail page URL (no login required)
        ats_url = f"{_BASE}/jobs/{job_id_num}"
        title = j.get("title", "").strip()
        company = j.get("companyName", "").strip()
        location = j.get("location", "").strip()
        role_type = j.get("roleType", "")
        job_type = j.get("jobType", "")
        salary = j.get("salary") or ""
        one_liner = j.get("companyOneLiner", "")
        batch = j.get("companyBatch", "")
        slug = j.get("companySlug", "")

        desc_parts = []
        if role_type: desc_parts.append(f"Role: {role_type}")
        if job_type: desc_parts.append(f"Type: {job_type}")
        if salary: desc_parts.append(f"Salary: {salary}")
        if one_liner: desc_parts.append(one_liner)
        if batch: desc_parts.append(f"YC batch: {batch}")
        description = " | ".join(desc_parts)

        return RawJob(
            source=self.name,
            title=title,
            company=company,
            location=location,
            posted_date=None,  # WAS doesn't expose posted_date in the list JSON
            ats_url=ats_url,
            ats_provider="workatastartup",  # we'll deep-scrape the WAS detail page
            description_hint=description,
        )
