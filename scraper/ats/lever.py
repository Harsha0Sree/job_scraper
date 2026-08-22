"""
Lever job-board parser.
URL pattern: https://jobs.lever.co/<org>/<job-id>
Lever pages are server-rendered with predictable structure.
"""
from __future__ import annotations

import re
from bs4 import BeautifulSoup

from .base import ATSParser, JobDetail, register_parser
from ..utils import html_to_text

import logging
log = logging.getLogger("scraper.ats.lever")

LEVER_HOSTS = ("jobs.lever.co",)


@register_parser
class LeverParser(ATSParser):
    provider = "lever"

    @classmethod
    def can_parse(cls, url: str) -> bool:
        return any(h in url for h in LEVER_HOSTS)

    def parse(self, url: str, html: str) -> JobDetail:
        soup = BeautifulSoup(html, "lxml")

        # Title: <h1 class="posting-headline"> or just <h1>
        title = ""
        h1 = soup.find("h1", class_=re.compile(r"posting-headline", re.I)) or soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

        # Company: from URL or from <title>
        company = ""
        m = re.search(r"jobs\.lever\.co/([^/]+)/", url)
        if m:
            company = m.group(1).replace("-", " ").title()
        if not company and soup.title:
            cm = re.search(r" at (.+?) - ", soup.title.get_text())
            if cm:
                company = cm.group(1).strip()

        # Location: <div class="posting-categories">
        location = ""
        loc = soup.find("div", class_=re.compile(r"location|sort-by-location", re.I))
        if loc:
            location = loc.get_text(strip=True)
        if not location:
            # Lever puts location in a .meta div under posting-header
            meta = soup.find("div", class_=re.compile(r"posting-categories|meta", re.I))
            if meta:
                location = meta.get_text(" ", strip=True)[:80]

        # Description: <div class="content-wrapper"> or #content
        desc_html = ""
        for sel in [
            {"class_": re.compile(r"content-wrapper", re.I)},
            {"class_": re.compile(r"posting-content", re.I)},
            {"id": "content"},
        ]:
            node = soup.find(attrs=sel)
            if node and len(node.get_text(strip=True)) > 200:
                desc_html = node.decode_contents()
                break
        if not desc_html:
            body = soup.find("body") or soup
            desc_html = body.decode_contents()

        return JobDetail(
            title=title, company=company, location=location,
            description=html_to_text(desc_html), description_html=desc_html,
            source_url=url, ats_provider=self.provider,
        )
