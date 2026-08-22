"""Ashby job-board parser. Extracts the window.__appData JSON blob."""
from __future__ import annotations

import json
import logging
import re

from .base import ATSParser, JobDetail, register_parser
from ..utils import html_to_text

log = logging.getLogger("scraper.ats.ashby")
ASHBY_HOSTS = ("jobs.ashbyhq.com",)

_APPDATA_START_RE = re.compile(r"window\.__appData\s*=\s*([{\"])")


@register_parser
class AshbyParser(ATSParser):
    provider = "ashby"

    @classmethod
    def can_parse(cls, url: str) -> bool:
        return any(h in url for h in ASHBY_HOSTS)

    def parse(self, url: str, html: str) -> JobDetail:
        data = _extract_appdata(html)
        if not data:
            log.warning("Ashby: could not extract __appData for %s", url)
            return JobDetail(
                description=html_to_text(html),
                description_html=html,
                source_url=url, ats_provider=self.provider,
                extra={"parse_error": "no_appdata"},
            )

        posting = data.get("posting", {}) or {}
        org = data.get("organization", {}) or {}

        title = posting.get("title", "") or ""
        company = org.get("name", "") or posting.get("companyName", "") or ""
        location = posting.get("locationName", "") or posting.get("location", "") or ""
        desc_html = posting.get("descriptionHtml", "") or ""

        extra_sections = []
        for key in ("responsibilitiesHtml", "requirementsHtml", "qualificationsHtml",
                    "benefitsHtml", "techStackHtml"):
            v = posting.get(key, "")
            if v:
                extra_sections.append(f"<h2>{key.replace('Html', '').title()}</h2>{v}")
        if extra_sections:
            desc_html = desc_html + "\n" + "\n".join(extra_sections)

        return JobDetail(
            title=title, company=company, location=location,
            description_html=desc_html, source_url=url,
            ats_provider=self.provider,
            extra={
                "department": posting.get("departmentName", ""),
                "employment_type": posting.get("employmentType", ""),
                "posted_at": posting.get("postedAt", ""),
            },
        )


def _extract_appdata(html: str) -> dict | None:
    m = _APPDATA_START_RE.search(html)
    if not m:
        return None
    start_quote = m.group(1)
    start_pos = m.end() - 1
    if start_quote == "{":
        json_str = _scan_balanced_braces(html, start_pos)
    else:
        json_str = _scan_quoted_string(html, start_pos, start_quote)
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        log.debug("Ashby JSON parse failed: %s", e)
        return None


def _scan_balanced_braces(s: str, start: int) -> str | None:
    assert s[start] == "{"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
    return None


def _scan_quoted_string(s: str, start: int, quote: str) -> str | None:
    assert s[start] == quote
    out = []
    i = start + 1
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            out.append(ch)
            out.append(s[i + 1])
            i += 2
            continue
        if ch == quote:
            return "".join(out)
        out.append(ch)
        i += 1
    return None
