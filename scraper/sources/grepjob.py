"""
grepjob.com source adapter.

List page: https://grepjob.com/?specialty=Backend,AI+%26+ML&seniority=entry+level&technology=Python
Pagination: ?page=N (12 jobs/page)

Each job card is a <div class="bg-gray-800 border ..."> containing:
  - <h3><a href="/jobs/<UUID>">Title</a></h3>     (internal link to detail)
  - <a href="https://ats.example.com/...">Apply</a> (external ATS link)
  - Company name in <span class="text-emerald-400">
  - Location/seniority/salary in spans
  - Description snippet
  - Tech tags in spans

We use the EXTERNAL Apply URL as the ats_url so the pipeline deep-scrapes
the actual ATS page (Greenhouse/Ashby/etc.) for the full description.
"""
from __future__ import annotations

import logging
import re
from typing import List
from urllib.parse import urljoin, urlencode, urlparse, parse_qsl

from bs4 import BeautifulSoup

from ..data_model import RawJob
from ..providers import detect_provider
from ..utils import parse_posted_date
from .base import SourceAdapter, register_adapter

log = logging.getLogger("scraper.sources.grepjob")

_BASE = "https://grepjob.com"


@register_adapter
class GrepJobAdapter(SourceAdapter):
    name = "grepjob"

    def fetch_jobs(self) -> List[RawJob]:
        max_pages = int(self.cfg.options.get("max_pages", 2))
        all_jobs: List[RawJob] = []
        for page_num in range(1, max_pages + 1):
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

    def _parse(self, html: str) -> List[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: List[RawJob] = []
        # Find all <h3> tags that contain a /jobs/ link
        for h3 in soup.find_all("h3"):
            a = h3.find("a", href=re.compile(r"^/jobs/"))
            if not a:
                continue
            # Walk up to find the card container
            card = h3
            for _ in range(8):
                card = card.parent
                if card is None: break
                cls = " ".join(card.get("class", [])) if card.get("class") else ""
                if "rounded-lg" in cls or "bg-gray-800" in cls:
                    break
            if not card or card.name != "div":
                continue
            try:
                job = self._parse_card(card, a)
                if job:
                    jobs.append(job)
            except Exception as e:
                log.debug("error parsing grepjob card: %s", e)
        return jobs

    def _parse_card(self, card, title_a):
        title = title_a.get_text(strip=True)
        internal_url = urljoin(_BASE, title_a["href"])

        # External Apply link (the ATS URL we want to deep-scrape)
        apply_a = card.find("a", href=re.compile(r"^https://"))
        apply_url = apply_a["href"] if apply_a else internal_url

        # Company
        company = ""
        company_span = card.find("span", class_=re.compile(r"text-emerald"))
        if company_span:
            company = company_span.get_text(strip=True)

        # Collect all span texts to find location/seniority/salary/time
        info_texts = []
        for span in card.find_all("span"):
            t = span.get_text(strip=True)
            if t and t not in ("Apply",) and len(t) < 100:
                info_texts.append(t)

        # Identify location (contains "Remote" or "Worldwide" or city names)
        location = ""
        for t in info_texts:
            tl = t.lower()
            if any(kw in tl for kw in ["remote", "worldwide", "anywhere"]):
                location = t
                break
        if not location:
            # Find a span with a location pattern (City, State/Country)
            for t in info_texts:
                if re.match(r"^[A-Z][a-zA-Z\s]+,\s*[A-Z][a-zA-Z\s]+$", t):
                    location = t
                    break

        # Identify time-ago
        time_text = ""
        for t in info_texts:
            if re.search(r"\bago\b", t, re.I) or re.search(r"\d+\s*(hour|day|week|month)", t, re.I):
                time_text = t
                break
        posted_date = parse_posted_date(time_text) if time_text else None

        # Identify seniority
        seniority = ""
        for t in info_texts:
            tl = t.lower()
            if any(kw in tl for kw in ["entry level", "intern", "junior", "mid level", "senior", "lead", "principal", "staff"]):
                seniority = t
                break

        # Identify salary
        salary = ""
        for t in info_texts:
            if re.search(r"[\$€£]\d+", t) or "/yr" in t or "/mo" in t:
                salary = t
                break

        # Tech tags (the spans with bg-gray-700)
        tech_tags = []
        for span in card.find_all("span", class_=re.compile(r"bg-gray-700")):
            t = span.get_text(strip=True)
            if t and t not in tech_tags:
                tech_tags.append(t)

        # Description snippet — grepjob includes a 1-2 sentence summary
        desc_snippet = ""
        # Find a <p> or text block that's not the title/company
        for p in card.find_all(["p", "div"]):
            t = p.get_text(" ", strip=True)
            if t and len(t) > 60 and t != title and not any(kw in t.lower() for kw in ["apply", "save"]):
                # Make sure it's not just a concatenation of tags
                if not all(word in tech_tags for word in t.split()):
                    desc_snippet = t
                    break

        desc_parts = []
        if seniority: desc_parts.append(f"Seniority: {seniority}")
        if salary: desc_parts.append(f"Salary: {salary}")
        if tech_tags: desc_parts.append(f"Tech: {', '.join(tech_tags[:10])}")
        if desc_snippet: desc_parts.append(desc_snippet)
        description = " | ".join(desc_parts)

        return RawJob(
            source=self.name,
            title=title,
            company=company,
            location=location,
            posted_date=posted_date,
            ats_url=apply_url,
            ats_provider=detect_provider(apply_url),
            description_hint=description,
            seniority=seniority,
        )
