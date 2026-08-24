"""Tests for pipeline internals that carry behaviour of their own."""
from __future__ import annotations

from scraper.config import Config, RuntimeConfig
from scraper.data_model import RawJob
from scraper.pipeline import _deep_scrape


def test_worker_crash_still_yields_a_timestamped_job():
    class ExplodingFetcher:
        def get(self, url, use_cache=True, headers=None):
            raise RuntimeError("boom")

    raw = RawJob(
        source="grepjob",
        title="Backend Engineer",
        company="Acme",
        location="Remote (Worldwide)",
        posted_date=None,
        ats_url="https://boards.greenhouse.io/acme/jobs/1",
    )

    jobs = _deep_scrape([raw], ExplodingFetcher(), Config(runtime=RuntimeConfig()))

    assert len(jobs) == 1
    assert jobs[0].error is not None
    assert "RuntimeError" in jobs[0].error
    assert jobs[0].scraped_at, "crashed jobs must still be stamped with scraped_at"
