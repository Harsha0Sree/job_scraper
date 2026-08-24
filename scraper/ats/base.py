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
    # Declarative dispatch: subclasses either set url_hosts (optionally
    # with url_requires) — drawn from scraper.providers.hosts_for() — or
    # override can_parse() entirely (catch-alls).
    url_hosts: tuple = ()
    url_requires: tuple = ()

    @classmethod
    def can_parse(cls, url: str) -> bool:
        if not cls.url_hosts:
            return False
        return (
            any(h in url for h in cls.url_hosts)
            and all(r in url for r in cls.url_requires)
        )

    def parse(self, url: str, html: str) -> JobDetail:
        raise NotImplementedError


_REGISTRY: list[type[ATSParser]] = []


def register_parser(cls: type[ATSParser]) -> type[ATSParser]:
    _REGISTRY.append(cls)
    return cls


def get_parser_for_url(url: str) -> Optional[ATSParser]:
    # Specific parsers win over declared catch-alls regardless of
    # registration order; fallbacks are consulted only afterwards.
    for cls in _REGISTRY:
        if getattr(cls, "is_fallback", False):
            continue
        if cls.can_parse(url):
            return cls()
    for cls in _REGISTRY:
        if getattr(cls, "is_fallback", False) and cls.can_parse(url):
            return cls()
    return None
