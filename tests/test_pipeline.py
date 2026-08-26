"""Tests for pipeline internals that carry behaviour of their own."""
from __future__ import annotations

from scraper.config import Config, RuntimeConfig
from scraper.data_model import RawJob, ScrapedJob
from scraper.pipeline import _deep_scrape, _partition
from scraper.state import StateManager
from scraper.utils import job_id


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


# ------------------------------ partition ---------------------------------- #

def _scraped(job_id: str, url: str, accepted=True, reason="all filters passed"):
    return ScrapedJob(
        job_id=job_id, source="grepjob", ats_url=url, ats_provider="greenhouse",
        title="Backend Engineer", company="Acme", location="Remote (Worldwide)",
        accepted=accepted, filter_reason=reason,
        is_location_match=True, is_category_match=True,
    )


def test_partition_routes_applied_jobs_out_of_the_queue(tmp_path):
    state = StateManager(tmp_path / "state.json")
    applied_url = "https://x/jobs/applied"
    state.mark_seen([_scraped(job_id(applied_url), applied_url)])
    state.mark_applied(job_id(applied_url), applied_url)

    fresh = _scraped("fresh1", "https://x/jobs/fresh")
    feedback_rejected = _scraped("fb1", "https://x/jobs/fb", accepted=False,
                                 reason="feedback: company 'Evil' was banned via feedback")
    normal_reject = _scraped("rej1", "https://x/jobs/rej", accepted=False,
                             reason="experience: senior-title:senior")

    buckets = _partition([_scraped(job_id(applied_url), applied_url),
                          fresh, feedback_rejected, normal_reject], state)

    assert [j.job_id for j in buckets["qualifying"]] == ["fresh1"]
    assert buckets["applied_seen"] and buckets["applied_seen"][0].job_id == job_id(applied_url)
    assert buckets["feedback_rejected"] and buckets["feedback_rejected"][0].job_id == "fb1"
    assert buckets["has_experience"] and buckets["has_experience"][0].job_id == "rej1"
