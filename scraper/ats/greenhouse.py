"""Greenhouse job-board parser."""
from __future__ import annotations

import re
from bs4 import BeautifulSoup

from .base import ATSParser, JobDetail, register_parser
from ..providers import hosts_for
from ..utils import html_to_text

import logging
log = logging.getLogger("scraper.ats.greenhouse")

GREENHOUSE_HOSTS = hosts_for("greenhouse")


@register_parser
class GreenhouseParser(ATSParser):
    provider = "greenhouse"
    url_hosts = GREENHOUSE_HOSTS

    def parse(self, url: str, html: str) -> JobDetail:
        soup = BeautifulSoup(html, "lxml")

        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
        if not title and soup.title:
            m = re.search(r"Job Application for (.+?) at ", soup.title.get_text())
            if m:
                title = m.group(1).strip()

        company = ""
        if soup.title:
            m = re.search(r" at (.+?)$", soup.title.get_text().strip())
            if m:
                company = m.group(1).strip()

        location = ""
        loc_node = soup.find(class_=re.compile(r"location", re.I))
        if loc_node:
            location = loc_node.get_text(strip=True)
        if not location and h1:
            sib = h1.find_next(string=True)
            if sib and sib.strip() and len(sib.strip()) < 80:
                location = sib.strip()

        desc_html = ""
        for selector in [
            {"class_": re.compile(r"job__description", re.I)},
            {"class_": re.compile(r"job-description", re.I)},
            {"class_": re.compile(r"job-post-container", re.I)},
            {"class_": re.compile(r"job-post", re.I)},
            {"id": "content"},
        ]:
            node = soup.find(attrs=selector)
            if node and len(node.get_text(strip=True)) > 200:
                desc_html = node.decode_contents()
                break
        if not desc_html:
            body = soup.find("body") or soup
            desc_html = body.decode_contents()

        desc_text = html_to_text(desc_html)
        # Strip "Back to jobs New <Title> <Loc> Apply About <Company>" prefix
        desc_text = re.sub(
            r"^Back to jobs.*?About\s+[A-Z][\w&.,'\- ]+?\s*\n",
            "",
            desc_text,
            count=1,
            flags=re.DOTALL,
        )

        return JobDetail(
            title=title, company=company, location=location,
            description=desc_text, description_html=desc_html,
            source_url=url, ats_provider=self.provider,
        )
