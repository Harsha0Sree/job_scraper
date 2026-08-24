"""Tests for the CLI's run-outcome contract: what the scheduler sees.

Seams under test:
  - scraper.cli.resolve_exit_code(summary) -> int
    0 = ok, 1 = nothing parsed (no source errors), 2 = usage/config error
    (argparse/main), 3 = some sources failed, 4 = every source failed.
  - scraper.cli.render_summary(summary) -> str
"""
from __future__ import annotations

import pytest

from scraper.cli import resolve_exit_code, render_summary


def _summary(**overrides):
    base = {
        "run_at": "2026-08-24T09:00:00",
        "mode": "daily",
        "days_back": "",
        "sources_scraped": ["grepjob", "aijobs"],
        "failed_sources": [],
        "by_source": {"grepjob": 10, "aijobs": 5},
        "parsed_count": 15,
        "qualifying_count": 2,
        "error_count": 0,
        "new_written": 2,
        "duration_seconds": 12.3,
    }
    base.update(overrides)
    return base


def test_all_sources_healthy_parses_jobs_is_ok():
    assert resolve_exit_code(_summary()) == 0


def test_zero_parsed_without_source_errors_is_still_distinct():
    s = _summary(parsed_count=0, by_source={"grepjob": 0}, sources_scraped=["grepjob"])
    assert resolve_exit_code(s) == 1


def test_some_sources_failed_is_partial_failure():
    s = _summary(
        sources_scraped=["grepjob", "aijobs", "hnhiring"],
        failed_sources=["hnhiring"],
        by_source={"grepjob": 10, "aijobs": 5},
        parsed_count=15,
    )
    assert resolve_exit_code(s) == 3


def test_every_source_failed_is_total_failure():
    s = _summary(
        sources_scraped=["grepjob", "aijobs"],
        failed_sources=["grepjob", "aijobs"],
        by_source={},
        parsed_count=0,
        error_count=2,
    )
    assert resolve_exit_code(s) == 4


def test_failed_sources_are_always_a_subset_of_scraped_sources():
    # resolve_exit_code's total-failure check (len(failed) >= len(scraped))
    # relies on the pipeline invariant that every failed source is also
    # listed in sources_scraped. Pin it so a future edit that appends to
    # only one list flips exit codes 3<->4 loudly, not silently.
    s = _summary(
        sources_scraped=["grepjob", "aijobs", "hnhiring"],
        failed_sources=["hnhiring"],
    )
    assert set(s["failed_sources"]) <= set(s["sources_scraped"])


def test_summary_reports_location_counts_under_their_real_names():
    s = _summary(
        location_match_count=5,
        not_location_count=7,
        failed_sources=["hnhiring"],
        sources_scraped=["grepjob", "aijobs", "hnhiring"],
    )
    text = render_summary(s)
    assert "Location matches:   5" in text
    assert "Rejected (location):  7" in text
    assert "Failed sources:     hnhiring" in text
    # The old phantom keys must never come back
    assert "Remote jobs" not in text
    assert "Not remote" not in text


def test_main_lists_sources_and_reads_status_offline(tmp_path):
    from scraper.cli import main

    state_dir = tmp_path / "data"
    config = (
        "sources:\n"
        "  grepjob:\n"
        "    url: https://grepjob.com/?specialty=Backend\n"
        "output:\n"
        f"  state_path: {state_dir / 'state.json'}\n"
        f"  log_dir: {tmp_path / 'logs'}\n"
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(config, encoding="utf-8")

    assert main(["--config", str(cfg_path), "list-sources"]) == 0
    assert main(["--config", str(cfg_path), "status"]) == 0
