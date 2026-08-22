"""
Source adapter base class.

Each source (startups.gallery, hnhiring, etc.) is implemented as a class
that inherits from SourceAdapter and produces a list of RawJob objects.

The adapter is responsible for:
  - Fetching the listing page(s) from the source URL
  - Parsing the HTML/JSON to extract individual job entries
  - Returning a list of RawJob objects (title, company, location, posted_date, ats_url)

The pipeline then takes over to deep-scrape the ATS detail page for each
RawJob and apply filters.
"""
from __future__ import annotations

import logging
from typing import List

from ..config import SourceConfig
from ..data_model import RawJob
from ..fetcher import Fetcher

log = logging.getLogger("scraper.sources.base")


class SourceAdapter:
    """Abstract source adapter."""
    name: str = "unknown"

    def __init__(self, source_cfg: SourceConfig, fetcher: Fetcher):
        self.cfg = source_cfg
        self.fetcher = fetcher

    def fetch_jobs(self) -> List[RawJob]:
        """Fetch and parse all jobs from this source. Returns a list of RawJob."""
        raise NotImplementedError


_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register_adapter(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Decorator: register a source adapter by its `name` attribute."""
    if not cls.name or cls.name == "unknown":
        raise ValueError(f"adapter {cls} must set a non-empty `name`")
    _REGISTRY[cls.name] = cls
    return cls


def get_adapter(source_cfg: SourceConfig, fetcher: Fetcher) -> SourceAdapter:
    """
    Look up an adapter by its `adapter` field in source config and
    instantiate it. Raises if the adapter is not registered.
    """
    name = source_cfg.adapter or source_cfg.name
    if name not in _REGISTRY:
        raise ValueError(
            f"no adapter registered for '{name}'. "
            f"Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name](source_cfg, fetcher)
