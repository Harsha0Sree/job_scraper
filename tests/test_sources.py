"""Tests for all 7 source adapters — uses saved HTML fixtures."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scraper.config import SourceConfig, HttpConfig
from scraper.fetcher import FetchResult
from scraper.sources import get_adapter

FIXTURES = Path(__file__).parent / "fixtures"


def _make_fetcher(html: str):
    """Create a mock Fetcher that always returns the given HTML."""
    fetcher = MagicMock()
    fetcher.get.return_value = FetchResult(
        url="http://test", status=200, text=html,
    )
    return fetcher


def _make_source_cfg(name: str, adapter: str, url: str, **opts):
    return SourceConfig(name=name, enabled=True, adapter=adapter, url=url, options=opts)


# --------------------------- startups.gallery ----------------------------- #

def test_startups_gallery_parses_jobs():
    html = (FIXTURES / "startups_gallery.html").read_text(encoding="utf-8")
    cfg = _make_source_cfg("startups_gallery", "startups_gallery",
                            "https://startups.gallery/jobs?location=remote")
    adapter = get_adapter(cfg, _make_fetcher(html))
    jobs = adapter.fetch_jobs()
    assert len(jobs) >= 20, f"expected >= 20 jobs, got {len(jobs)}"
    j = jobs[0]
    assert j.title, "title empty"
    assert j.ats_url.startswith("https://")
    assert j.source == "startups_gallery"


# ------------------------------- hnhiring --------------------------------- #

def test_hnhiring_parses_jobs():
    html = (FIXTURES / "hnhiring.html").read_text(encoding="utf-8")
    cfg = _make_source_cfg("hnhiring", "hnhiring",
                            "https://hnhiring.com/locations/remote")
    adapter = get_adapter(cfg, _make_fetcher(html))
    jobs = adapter.fetch_jobs()
    assert len(jobs) >= 50, f"expected >= 50 jobs, got {len(jobs)}"
    j = jobs[0]
    assert j.title, "title empty"
    assert j.ats_url, "ats_url empty"
    assert j.source == "hnhiring"


# --------------------------------- no_wb ---------------------------------- #

def test_no_wb_parses_companies():
    html = (FIXTURES / "no_wb.html").read_text(encoding="utf-8")
    cfg = _make_source_cfg("no_wb", "no_wb", "https://www.no-wb.org/", max_pages=1)
    adapter = get_adapter(cfg, _make_fetcher(html))
    jobs = adapter.fetch_jobs()
    assert len(jobs) >= 20, f"expected >= 20 companies, got {len(jobs)}"
    j = jobs[0]
    assert j.company, "company empty"
    assert j.ats_url.startswith("http")


# -------------------------------- aijobs ---------------------------------- #

def test_aijobs_parses_jobs():
    html = (FIXTURES / "aijobs.html").read_text(encoding="utf-8")
    cfg = _make_source_cfg("aijobs", "aijobs", "https://aijobs.net/?location=remote", max_pages=1)
    adapter = get_adapter(cfg, _make_fetcher(html))
    jobs = adapter.fetch_jobs()
    assert len(jobs) >= 30, f"expected >= 30 jobs, got {len(jobs)}"
    j = jobs[0]
    assert j.title, "title empty"
    assert "aijobs.net" in j.ats_url


# ----------------------------- workatastartup ----------------------------- #

def test_workatastartup_parses_jobs():
    html = (FIXTURES / "workatastartup.html").read_text(encoding="utf-8")
    cfg = _make_source_cfg("workatastartup", "workatastartup",
                            "https://www.workatastartup.com/jobs", max_pages=1)
    adapter = get_adapter(cfg, _make_fetcher(html))
    jobs = adapter.fetch_jobs()
    assert len(jobs) >= 20, f"expected >= 20 jobs, got {len(jobs)}"
    j = jobs[0]
    assert j.title, "title empty"
    assert j.company, "company empty"
    assert "workatastartup.com/jobs/" in j.ats_url


# ------------------------------- grepjob ---------------------------------- #

def test_grepjob_parses_jobs():
    html = (FIXTURES / "grepjob.html").read_text(encoding="utf-8")
    cfg = _make_source_cfg("grepjob", "grepjob",
                            "https://grepjob.com/?specialty=Backend", max_pages=1)
    adapter = get_adapter(cfg, _make_fetcher(html))
    jobs = adapter.fetch_jobs()
    assert len(jobs) >= 5, f"expected >= 5 jobs, got {len(jobs)}"
    j = jobs[0]
    assert j.title, "title empty"
    assert j.ats_url, "ats_url empty"
