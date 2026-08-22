"""
Common data model: RawJob (from a listing) -> ScrapedJob (after deep-scrape + filter).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class RawJob:
    """A job parsed from a source listing page (before deep-scraping)."""
    source: str
    title: str
    company: str
    location: str
    posted_date: Optional[date]
    ats_url: str
    ats_provider: str = "unknown"
    description_hint: str = ""
    seniority: str = ""           # e.g. "Entry level", "Mid-level" (from ATS tag)
    job_id: str = ""

    def __post_init__(self) -> None:
        if not self.job_id:
            from .utils import job_id
            self.job_id = job_id(self.ats_url or f"{self.source}:{self.title}:{self.company}")


@dataclass
class ScrapedJob:
    # Identity
    job_id: str
    source: str
    ats_url: str
    ats_provider: str

    # Display fields
    title: str = ""
    company: str = ""
    location: str = ""
    posted_date: Optional[date] = None

    # Full description
    description: str = ""
    description_html: str = ""
    seniority: str = ""           # from ATS tag (e.g. "Entry level")

    # Filter results
    is_location_match: bool = False
    location_type: str = ""       # "remote_anywhere", "remote_india", "onsite_india"
    is_category_match: bool = False
    accepted: bool = False
    filter_reason: str = ""
    category_signals: List[str] = field(default_factory=list)
    experience_signals: List[str] = field(default_factory=list)
    years_mentioned: List[str] = field(default_factory=list)

    # Run metadata
    scraped_at: str = ""
    error: Optional[str] = None

    @property
    def description_preview(self) -> str:
        from .utils import truncate
        return truncate(self.description, 600)

    @classmethod
    def from_raw(cls, raw: RawJob) -> "ScrapedJob":
        return cls(
            job_id=raw.job_id,
            source=raw.source,
            ats_url=raw.ats_url,
            ats_provider=raw.ats_provider,
            title=raw.title,
            company=raw.company,
            location=raw.location,
            posted_date=raw.posted_date,
            description=raw.description_hint,
            seniority=raw.seniority,
        )
