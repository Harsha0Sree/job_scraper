"""Tests for StateManager: applied tracking + analysis-ready seen records."""
from __future__ import annotations

from scraper.data_model import ScrapedJob
from scraper.state import StateManager


def _job(job_id: str, url: str, **kw) -> ScrapedJob:
    defaults = dict(
        source="grepjob", title="Backend Engineer", company="Acme",
        location="Remote (Worldwide)", accepted=True,
        ats_provider="greenhouse", seniority="Entry level",
        filter_reason="all filters passed",
        description="We want 3 yrs of Go.",
    )
    defaults.update(kw)
    return ScrapedJob(job_id=job_id, ats_url=url, **defaults)


def test_mark_applied_round_trips(tmp_path):
    state = StateManager(tmp_path / "state.json")
    assert state.is_applied("abc") is False

    state.mark_applied("abc", "https://x/jobs/1", note="recruiter call")
    state.save()

    reloaded = StateManager(tmp_path / "state.json")
    assert reloaded.is_applied("abc") is True
    records = reloaded.applied_records()
    assert len(records) == 1
    assert records[0]["job_id"] == "abc"
    assert records[0]["ats_url"] == "https://x/jobs/1"
    assert records[0]["note"] == "recruiter call"
    assert records[0]["applied_at"]


def test_seen_jobs_keep_filter_metadata_for_feedback_analysis(tmp_path):
    state = StateManager(tmp_path / "state.json")
    state.mark_seen([_job("j1", "https://x/jobs/1")])
    state.save()

    record = StateManager(tmp_path / "state.json").job_record("j1")
    assert record["title"] == "Backend Engineer"
    assert record["company"] == "Acme"
    assert record["location"] == "Remote (Worldwide)"
    assert record["seniority"] == "Entry level"
    assert record["filter_reason"] == "all filters passed"
    assert "3 yrs" in record["description_preview"]
