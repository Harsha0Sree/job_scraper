"""
Generic fallback parser for ATS providers we don't have a specialized
parser for (company career pages, LinkedIn, etc.).
"""
from __future__ import annotations

import logging
import re
from bs4 import BeautifulSoup

from .base import ATSParser, JobDetail, register_parser
from ..utils import html_to_text

log = logging.getLogger("scraper.ats.generic")

_DESC_SELECTORS = [
    {"name": "div", "attrs": {"id": "job-description"}},
    {"name": "div", "attrs": {"id": "jobDescription"}},
    {"name": "div", "attrs": {"class_": re.compile(r"job-description", re.I)}},
    {"name": "div", "attrs": {"class_": re.compile(r"jobDescription", re.I)}},
    {"name": "div", "attrs": {"class_": re.compile(r"description", re.I)}},
    {"name": "div", "attrs": {"class_": re.compile(r"content", re.I)}},
    {"name": "main"},
    {"name": "article"},
]


@register_parser
class GenericParser(ATSParser):
    provider = "generic"
    is_fallback = True

    @classmethod
    def can_parse(cls, url: str) -> bool:
        return True

    def parse(self, url: str, html: str) -> JobDetail:
        soup = BeautifulSoup(html, "lxml")

        title = ""
        for sel in (soup.find("h1"), soup.find("meta", attrs={"property": "og:title"}),
                    soup.find("title")):
            if sel:
                txt = sel.get("content", "") if sel.name == "meta" else sel.get_text(strip=True)
                if txt:
                    title = txt.strip()
                    title = re.sub(r"\s*[|·\-—]\s*.*$", "", title).strip()
                    break

        desc_html = ""
        for sel in _DESC_SELECTORS:
            node = soup.find(sel["name"], attrs=sel.get("attrs", {}))
            if node:
                desc_html = node.decode_contents()
                break
        if not desc_html:
            body = soup.find("body") or soup
            for tag in body.find_all(["script", "style", "noscript", "header", "footer", "nav"]):
                tag.decompose()
            desc_html = body.decode_contents()

        return JobDetail(
            title=title, company="", location="",
            description=html_to_text(desc_html), description_html=desc_html,
            source_url=url, ats_provider=self.provider,
        )
