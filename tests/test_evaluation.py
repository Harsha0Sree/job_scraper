"""Tests for the job evaluation seam: a raw listing becomes a filtered ScrapedJob.

The seam under test is scraper.evaluation.evaluate(raw, fetcher, filters_cfg).
Network is replaced by a stub transport speaking Fetcher's public shape; ATS
pages are the real HTML fixtures in tests/fixtures/.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scraper.config import (
    FiltersConfig, CategoryFilter, LocationFilter, ZeroExperienceFilter,
)
from scraper.data_model import RawJob
from scraper.evaluation import evaluate
from scraper.fetcher import FetchResult

FIXTURES = Path(__file__).parent / "fixtures"


class StubFetcher:
    """Test double implementing Fetcher.get's public interface."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requested_urls: list[str] = []

    def get(self, url, use_cache=True, headers=None):
        self.requested_urls.append(url)
        r = self.responses.get(url)
        if r is None:
            return FetchResult(url=url, status=0, text="", error="stub: no response")
        return r


@pytest.fixture
def cfg() -> FiltersConfig:
    return FiltersConfig(
        category=CategoryFilter(
            backend_title_keywords=["backend", "software engineer", "platform engineer",
                                     "python developer", "fullstack"],
            ai_title_keywords=["ai engineer", "ml engineer", "machine learning", "data scientist"],
            exclude_title_keywords=["frontend", "mobile", "designer", "sales", "marketing",
                                     "product manager", "security engineer"],
        ),
        location=LocationFilter(
            remote_anywhere_patterns=["remote (worldwide)", "remote, worldwide",
                                        "work from anywhere", "fully remote"],
            remote_india_patterns=["remote (india)", "remote, india"],
            india_locations=["bangalore", "mumbai", "delhi", "hyderabad", "pune",
                              "chennai", "bengaluru", "india"],
            restricted_remote_patterns=["remote (us)", "remote (europe)", "remote (uk)"],
            non_remote_non_india_patterns=[],
        ),
        zero_experience=ZeroExperienceFilter(
            senior_keywords=["senior", "lead", "principal", "staff", "manager", "director"],
            seniority_levels_rejected=["senior-level", "mid-level"],
            min_years_threshold=1,
            min_years_patterns=[r"(\d+)\s*\+\s*years?"],
            entry_level_signals=["entry level", "junior", "new grad", "internship",
                                  "fresher", "0-2 years"],
            entry_level_seniority_levels=["entry level", "intern", "junior"],
            include_no_mention=False,
        ),
    )


def _raw(**overrides) -> RawJob:
    defaults = dict(
        source="hnhiring",
        title="Junior Backend Engineer",
        company="Acme",
        location="Remote (India)",
        posted_date=None,
        ats_url="https://boards.greenhouse.io/acme/jobs/123",
    )
    defaults.update(overrides)
    return RawJob(**defaults)


def test_text_only_job_is_evaluated_from_listing_hint_without_fetch(cfg):
    raw = _raw(
        ats_url="hnhiring://text/abc123",
        title="Junior Backend Engineer",
        description_hint="We hire entry level engineers. Python and Go.",
    )
    job = evaluate(raw, StubFetcher(), cfg)

    assert job.error is None
    assert job.description == "We hire entry level engineers. Python and Go."
    assert job.accepted is True
    assert job.location_type == "remote_india"
    assert job.is_location_match and job.is_category_match
    assert any(s.startswith("signal:") for s in job.experience_signals)


def test_greenhouse_detail_overrides_listing_and_filters_on_merged_fields(cfg):
    html = FIXTURES.joinpath("greenhouse.html").read_text(encoding="utf-8")
    url = "https://boards.greenhouse.io/enterpret/jobs/7821474003"
    fetcher = StubFetcher({url: FetchResult(url=url, status=200, text=html)})
    raw = _raw(
        source="grepjob",
        title="Engineer",
        company="Unknown Co",
        location="Remote (Worldwide)",
        ats_url=url,
    )

    job = evaluate(raw, fetcher, cfg)

    assert fetcher.requested_urls == [url]
    assert job.error is None
    # Detail-page fields override the listing's
    assert job.title == "Principal Engineer, Core Product"
    assert job.company == "Enterpret"
    # The merged title matches no backend/AI keyword -> rejected at category,
    # with the location still recorded as a match for the audit trail.
    assert job.is_location_match is True
    assert job.is_category_match is False
    assert job.accepted is False
    assert job.filter_reason.startswith("category:")
    assert job.description


def test_fetch_failure_is_recorded_as_error_and_job_is_not_filtered(cfg):
    url = "https://boards.greenhouse.io/acme/jobs/404"
    fetcher = StubFetcher({
        url: FetchResult(url=url, status=404, text="", error="HTTP 404"),
    })
    raw = _raw(title="Backend Engineer", location="Remote (Worldwide)", ats_url=url)

    job = evaluate(raw, fetcher, cfg)

    assert job.error is not None
    assert job.error.startswith("fetch_failed")
    assert job.accepted is False
    assert job.filter_reason == ""


def test_seniority_tag_from_ats_extra_rejects_mid_level(cfg):
    from scraper.ats.base import ATSParser, JobDetail, register_parser, _REGISTRY

    class FakeATS(ATSParser):
        provider = "fakeats"

        @classmethod
        def can_parse(cls, url):
            return "test-ats.example" in url

        def parse(self, url, html):
            return JobDetail(
                title="Software Engineer",
                company="Tagged Co",
                extra={"level": "Mid-Level"},
                source_url=url,
            )

    register_parser(FakeATS)
    try:
        url = "https://test-ats.example/jobs/1"
        fetcher = StubFetcher({url: FetchResult(url=url, status=200, text="<html></html>")})
        raw = _raw(source="grepjob", title="Software Engineer",
                   location="Remote (Worldwide)", ats_url=url)

        job = evaluate(raw, fetcher, cfg)

        assert job.seniority == "Mid-Level"
        assert job.accepted is False
        assert "seniority:mid-level" in job.filter_reason
    finally:
        _REGISTRY.remove(FakeATS)
