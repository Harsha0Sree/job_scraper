"""startups.gallery source adapter."""
from __future__ import annotations

import logging
import re
from typing import List

from bs4 import BeautifulSoup, Tag

from ..data_model import RawJob
from ..providers import detect_provider
from ..utils import parse_posted_date
from .base import SourceAdapter, register_adapter

log = logging.getLogger("scraper.sources.startups_gallery")

ATS_URL_RE = re.compile(
    r"^https://(?:"
    r"job-boards\.greenhouse\.io|jobs\.ashbyhq\.com|jobs\.lever\.co|"
    r"boards\.greenhouse\.io|jobs\.workable\.com|careers\.smartrecruiters\.com"
    r")/",
    re.IGNORECASE,
)
GENERIC_ATS_HINTS = (
    "greenhouse.io", "ashbyhq.com", "lever.co", "workable.com",
    "smartrecruiters.com", "tally.so", "linkedin.com/jobs",
)


@register_adapter
class StartupsGalleryAdapter(SourceAdapter):
    name = "startups_gallery"

    def fetch_jobs(self) -> List[RawJob]:
        url = self.cfg.url
        log.info("[%s] fetching %s", self.name, url)
        r = self.fetcher.get(url, use_cache=False)
        if not r.ok:
            log.error("[%s] fetch failed: %s (status=%s)", self.name, r.error, r.status)
            return []
        jobs = self._parse(r.text)
        log.info("[%s] parsed %d jobs", self.name, len(jobs))
        return jobs

    def _parse(self, html: str) -> List[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        seen_urls: set[str] = set()
        jobs: List[RawJob] = []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith("http"):
                continue
            if not (ATS_URL_RE.match(href) or any(h in href for h in GENERIC_ATS_HINTS)):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)

            title, meta_text = _extract_title_and_meta(a)
            if not title:
                continue
            company, location, posted = _parse_meta(meta_text)
            jobs.append(RawJob(
                source=self.name,
                title=title,
                company=company,
                location=location,
                posted_date=posted,
                ats_url=href,
                ats_provider=detect_provider(href),
            ))
        return jobs


def _extract_title_and_meta(anchor: Tag):
    title = ""
    meta_text = ""
    for tag_name in ("h1", "h2", "h3"):
        h = anchor.find(tag_name)
        if h:
            title = h.get_text(" ", strip=True)
            if title:
                break
    if not meta_text:
        p = anchor.find("p")
        if p:
            meta_text = p.get_text(" ", strip=True)
    if not meta_text:
        t = anchor.find("time")
        if t:
            meta_text = t.get_text(" ", strip=True)
    if not title or not meta_text:
        blocks = _distinct_text_blocks(anchor)
        if not title and blocks:
            title = blocks[0]
        if not meta_text and len(blocks) >= 2:
            meta_text = blocks[1]
    return title, meta_text


def _distinct_text_blocks(node: Tag):
    blocks = []
    for child in node.find_all(recursive=True):
        if child.name in ("h1", "h2", "h3", "h4", "p", "time", "span", "div"):
            txt = child.get_text(" ", strip=True)
            if txt and txt not in blocks:
                if not child.find(["h1", "h2", "h3", "h4", "p", "time", "div"]):
                    blocks.append(txt)
    return blocks


def _parse_meta(meta_text: str):
    if not meta_text:
        return "", "", None
    parts = [p.strip() for p in meta_text.split("·") if p.strip()]
    if not parts:
        return "", "", None
    posted = None
    for i, part in enumerate(parts):
        if re.search(r"posted\s+on", part, re.IGNORECASE):
            posted = parse_posted_date(part)
            parts = parts[:i] + parts[i + 1:]
            break
    if not parts:
        return "", "", posted
    if len(parts) == 1:
        return parts[0], "", posted
    return parts[0], " · ".join(parts[1:]), posted
