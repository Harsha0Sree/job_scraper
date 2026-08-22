"""
Base class for ATS (Applicant Tracking System) parsers.
Each parser takes raw HTML from a job detail page and produces a JobDetail.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("scraper.ats")


@dataclass
class JobDetail:
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    description_html: str = ""
    source_url: str = ""
    ats_provider: str = "unknown"
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.description_html and not self.description:
            from ..utils import html_to_text
            self.description = html_to_text(self.description_html)


class ATSParser:
    provider: str = "unknown"

    @classmethod
    def can_parse(cls, url: str) -> bool:
        raise NotImplementedError

    def parse(self, url: str, html: str) -> JobDetail:
        raise NotImplementedError


_REGISTRY: list[type[ATSParser]] = []


def register_parser(cls: type[ATSParser]) -> type[ATSParser]:
    _REGISTRY.append(cls)
    return cls


def get_parser_for_url(url: str) -> Optional[ATSParser]:
    for cls in _REGISTRY:
        if cls.can_parse(url):
            return cls()
    return None
