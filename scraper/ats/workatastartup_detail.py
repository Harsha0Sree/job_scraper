"""
workatastartup.com detail-page parser.
URL pattern: https://www.workatastartup.com/jobs/<id>

The page has the same data-page JSON structure as the list page, but with
props.job containing the full descriptionHtml.
"""
from __future__ import annotations

import html
import json
import logging
import re

from .base import ATSParser, JobDetail, register_parser
from ..providers import hosts_for
from ..utils import html_to_text

log = logging.getLogger("scraper.ats.workatastartup_detail")


_WAS_HOSTS = hosts_for("workatastartup")


@register_parser
class WorkAtAStartupDetailParser(ATSParser):
    provider = "workatastartup"
    url_hosts = _WAS_HOSTS
    url_requires = ("/jobs/",)

    def parse(self, url: str, html_text: str) -> JobDetail:
        m = re.search(r'data-page="([^"]+)"', html_text)
        if not m:
            log.warning("WAS: no data-page found for %s", url)
            return JobDetail(
                description=html_to_text(html_text),
                description_html=html_text,
                source_url=url, ats_provider=self.provider,
                extra={"parse_error": "no_data_page"},
            )
        try:
            data = json.loads(html.unescape(m.group(1)))
        except json.JSONDecodeError as e:
            log.error("WAS data-page parse failed: %s", e)
            return JobDetail(
                source_url=url, ats_provider=self.provider,
                extra={"parse_error": str(e)},
            )

        props = data.get("props", {})
        job = props.get("job", {}) or {}
        company = props.get("company", {}) or {}

        title = job.get("title", "") or ""
        company_name = company.get("name", "") or ""
        location = job.get("location", "") or ""
        desc_html = job.get("descriptionHtml", "") or ""
        # Add interview process as a section
        ip = job.get("interviewProcessHtml", "")
        if ip:
            desc_html = desc_html + f"<h2>Interview Process</h2>{ip}"

        # Company description
        company_desc = company.get("description", "") or company.get("hiringDescriptionHtml", "") or ""
        if company_desc and company_desc not in desc_html:
            desc_html = f"<h2>About {company_name}</h2>{company_desc}" + desc_html

        # Tech stack
        tech = company.get("techDescriptionHtml", "") or ""
        if tech:
            desc_html = desc_html + f"<h2>Tech Stack</h2>{tech}"

        # Skills
        skills = job.get("skills", [])
        if skills:
            skills_html = ", ".join(skills) if isinstance(skills, list) else str(skills)
            desc_html = desc_html + f"<h2>Skills</h2><p>{skills_html}</p>"

        # Salary, equity, visa
        salary = job.get("salaryRange", "") or ""
        equity = job.get("equityRange", "") or ""
        visa = job.get("sponsorsVisa", False)
        min_exp = job.get("minExperience", 0)

        extra = {
            "salary": salary,
            "equity": equity,
            "sponsors_visa": visa,
            "min_experience": min_exp,
            "company_industry": company.get("industry", ""),
            "company_batch": company.get("batch", ""),
        }

        return JobDetail(
            title=title, company=company_name, location=location,
            description_html=desc_html, source_url=url,
            ats_provider=self.provider, extra=extra,
        )
