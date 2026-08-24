"""
aijobs.net detail-page parser.
URL pattern: https://aijobs.net/job/<slug>/

The detail page has the full job description in the main content area,
with sections like Tasks, Perks/Benefits, Skills/Tech-stack, Education.
"""
from __future__ import annotations

import re
from bs4 import BeautifulSoup

from .base import ATSParser, JobDetail, register_parser
from ..providers import hosts_for
from ..utils import html_to_text

import logging
log = logging.getLogger("scraper.ats.aijobs_detail")

_AIJOBS_HOSTS = hosts_for("aijobs")


@register_parser
class AiJobsDetailParser(ATSParser):
    provider = "aijobs"
    url_hosts = _AIJOBS_HOSTS
    url_requires = ("/job/",)

    def parse(self, url: str, html: str) -> JobDetail:
        soup = BeautifulSoup(html, "lxml")

        # Title from <title> or <h1>
        title = ""
        if soup.title:
            m = re.match(r"(.+?)(?:\s+-\s+Remote)?\s*\|\s*aijobs", soup.title.get_text())
            if m:
                title = m.group(1).strip()
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        # Company: look for "@ company" pattern
        company = ""
        m = re.search(r"@\s*([A-Za-z0-9][\w&.,'\- ]+?)(?:\s+(?:Apply|Save|$))", soup.get_text(" "))
        if m:
            company = m.group(1).strip()

        # Location: the detail page shows location right after the title.
        # Format: "Title Location R Salary Seniority Type @ Company Apply ..."
        # We extract the location from the text between the title and the salary.
        location = ""
        if title:
            full_text = soup.get_text(" ", strip=True)
            # Find the title in the text, then grab the next token
            idx = full_text.find(title)
            if idx >= 0:
                after = full_text[idx + len(title):].strip()
                # The next word(s) before "R" or salary or seniority
                # e.g. "Remote R USD 180K-240K ..." -> location = "Remote"
                # e.g. "Bengaluru, India R ..." -> location = "Bengaluru, India"
                m2 = re.match(r"\s*([^R]+?)(?:\s+R\s|\s+USD\s|\s+€\s|\s+£\s)", after)
                if m2:
                    location = m2.group(1).strip()
                    # Clean up common artifacts
                    location = re.sub(r"\s+", " ", location).strip()

        # Seniority: look for seniority badge
        seniority = ""
        for span in soup.find_all("span", class_=re.compile(r"text-bg-warning")):
            t = span.get_text(strip=True)
            if t and any(kw in t.lower() for kw in ["level", "senior", "mid", "entry", "intern", "junior", "lead", "principal"]):
                seniority = t
                break

        # Description: main content
        desc_html = ""
        main = soup.find("main") or soup.find("article") or soup.find(class_=re.compile(r"content|job-detail", re.I))
        if main:
            for tag in main.find_all(["nav", "footer", "header"]):
                tag.decompose()
            desc_html = main.decode_contents()
        if not desc_html:
            body = soup.find("body") or soup
            desc_html = body.decode_contents()

        desc_text = html_to_text(desc_html)
        desc_text = re.sub(r"^(?:Statistics Expert|AI Engineer|.*?Apply\s+Save\s+Copy link\s+Published\s+\d+[dhwm]\s*ago\s*)", "", desc_text, count=1, flags=re.DOTALL)

        return JobDetail(
            title=title, company=company, location=location,
            description=desc_text, description_html=desc_html,
            source_url=url, ats_provider=self.provider,
            extra={"seniority": seniority},
        )
