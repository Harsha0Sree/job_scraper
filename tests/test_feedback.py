"""Tests for the closed feedback loop (S5).

Seams under test:
  - feedback.append_entry / process_feedback: user feedback becomes auditable
    learned rules (data/learned_rules.yaml) and applied-state; processing is
    idempotent (entries are never applied twice).
  - LearnedRules.check(...): each rule type suppresses matching jobs with an
    explainable 'feedback:' reason.
"""
from __future__ import annotations

import json

import pytest

from scraper.data_model import ScrapedJob
from scraper.feedback import (
    FeedbackReport, LearnedRules, append_entry, load_entries, process_feedback,
    normalize_company,
)
from scraper.state import StateManager
from scraper.utils import job_id


def _seed_state(tmp_path, url="https://x/jobs/1",
                title="Platform Ninja Engineer", company="Acme Corp",
                location="Remote (US)", **record_kw):
    state = StateManager(tmp_path / "state.json")
    state.mark_seen([ScrapedJob(
        job_id=job_id(url), source="grepjob", ats_url=url,
        ats_provider="greenhouse", title=title, company=company,
        location=location, accepted=True,
        **record_kw,
    )])
    return state


def _paths(tmp_path):
    return dict(
        feedback_path=tmp_path / "feedback.yaml",
        rules_path=tmp_path / "learned_rules.yaml",
        processed_path=tmp_path / ".feedback_processed.json",
    )


# --------------------------- entry handling -------------------------------- #

def test_append_and_load_entries_round_trip(tmp_path):
    p = _paths(tmp_path)
    append_entry("https://x/jobs/1", action="reject",
                 violated=["category"], comment='"ninja" is not engineering',
                 path=p["feedback_path"])
    entries = load_entries(path=p["feedback_path"])
    assert len(entries) == 1
    assert entries[0].url == "https://x/jobs/1"
    assert entries[0].action == "reject"
    assert entries[0].violated == ["category"]
    assert "ninja" in entries[0].comment


def test_applied_action_marks_state_without_learning_rules(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path, title="Backend Engineer", company="Good Co")
    append_entry("https://x/jobs/1", action="applied", comment="applied!",
                 path=p["feedback_path"])

    report = process_feedback(state=state, **_paths(tmp_path),
                              senior_keywords=[], ai_keywords=[])

    assert state.is_applied(job_id("https://x/jobs/1")) is True
    assert report.applied_marked == ["https://x/jobs/1"]
    rules = LearnedRules.load(p["rules_path"])
    assert rules.banned_job_ids == set()
    assert rules.banned_companies == set()


def test_reject_learns_exact_job_and_company_with_provenance(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path)
    append_entry("https://x/jobs/1", action="reject", violated=["location"],
                 comment="US only", path=p["feedback_path"])

    report = process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules = LearnedRules.load(p["rules_path"])
    assert job_id("https://x/jobs/1") in rules.banned_job_ids
    assert normalize_company("Acme Corp") in rules.banned_companies
    prov = rules.provenance[f"company:{normalize_company('Acme Corp')}"]
    assert prov["from_url"] == "https://x/jobs/1"
    assert prov["constraint"] == "location"
    assert prov["comment"] == "US only"
    assert report.rules_learned  # something was learned


def test_processing_is_idempotent_across_runs(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path)
    append_entry("https://x/jobs/1", action="reject", violated=["category"],
                 comment="", path=p["feedback_path"])

    process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])
    rules1 = LearnedRules.load(p["rules_path"])
    report2 = process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules2 = LearnedRules.load(p["rules_path"])
    assert rules2.banned_job_ids == rules1.banned_job_ids
    assert report2.processed == 0


# ------------------------- constraint analysis ----------------------------- #

def test_experience_slip_yrs_abbreviation_becomes_learned_regex(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path, title="Backend Engineer",
                        description="You need 3 yrs of Go.")
    append_entry("https://x/jobs/1", action="reject", violated=["experience"],
                 comment="", path=p["feedback_path"])

    process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules = LearnedRules.load(p["rules_path"])
    assert r"(\d+)\s*yrs?\b" in rules.banned_years_regexes
    reason = rules.check("other", "Backend Engineer", "X", "Remote",
                         "Must have 5 yrs Rust")
    assert reason and "5 yrs" in reason and "feedback:" in reason


def test_experience_word_number_phrase_is_learned_verbatim(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path, title="Backend Engineer",
                        description="ideal for candidates with three years building systems")
    append_entry("https://x/jobs/1", action="reject", violated=["experience"],
                 comment="", path=p["feedback_path"])

    process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules = LearnedRules.load(p["rules_path"])
    assert "three years" in rules.banned_phrases


def test_experience_seniority_token_in_title_is_learned_once(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path, title="Sr. Platform Engineer",
                        description="")
    append_entry("https://x/jobs/1", action="reject", violated=["experience"],
                 comment="", path=p["feedback_path"])

    process_feedback(state=state, **p, senior_keywords=["senior"], ai_keywords=[])

    rules = LearnedRules.load(p["rules_path"])
    # \b sr \b word-boundary matching covers "Sr." titles too
    assert "sr" in [k.lower() for k in rules.banned_title_keywords]


def test_category_quoted_comment_phrases_ban_immediately(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path, title="Growth Backend Engineer",
                        description="")
    append_entry("https://x/jobs/1", action="reject", violated=["category"],
                 comment='this is really a "growth marketing" role',
                 path=p["feedback_path"])

    process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules = LearnedRules.load(p["rules_path"])
    assert "growth marketing" in rules.banned_phrases


def test_category_title_token_needs_two_offences_to_ban(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path, title="Ninja Growth Hacker",
                        description="")
    append_entry("https://x/jobs/1", action="reject", violated=["category"],
                 comment="", path=p["feedback_path"])
    process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules1 = LearnedRules.load(p["rules_path"])
    assert "ninja" not in rules1.banned_title_keywords  # one strike only

    state.mark_seen([ScrapedJob(
        job_id=job_id("https://x/jobs/2"), source="grepjob", ats_url="https://x/jobs/2",
        ats_provider="greenhouse", title="Code Ninja Rockstar",
        company="Beta LLC", location="Bengaluru", accepted=True,
        description="")])
    append_entry("https://x/jobs/2", action="reject", violated=["category"],
                 comment="", path=p["feedback_path"])
    process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules2 = LearnedRules.load(p["rules_path"])
    assert "ninja" in rules2.banned_title_keywords          # two offences
    assert "rockstar" not in rules2.banned_title_keywords   # seen only once


def test_core_terms_are_never_learned_from_category_feedback(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path, title="Data Engineer II",
                        description="")
    append_entry("https://x/jobs/1", action="reject", violated=["category"],
                 comment="", path=p["feedback_path"])

    process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules = LearnedRules.load(p["rules_path"])
    joined = [k.lower() for k in rules.banned_title_keywords]
    assert "data" not in joined and "engineer" not in joined


def test_location_string_ban_suppresses_same_location(tmp_path):
    p = _paths(tmp_path)
    state = _seed_state(tmp_path)
    append_entry("https://x/jobs/1", action="reject", violated=["location"],
                 comment="", path=p["feedback_path"])

    process_feedback(state=state, **p, senior_keywords=[], ai_keywords=[])

    rules = LearnedRules.load(p["rules_path"])
    assert "remote (us)" in rules.banned_locations
    assert rules.check("zzz", "Any Title", "Co", "Remote (US)", "") is not None


# ------------------------------ checking ----------------------------------- #

def test_check_reasons_for_every_rule_type(tmp_path):
    rules = LearnedRules()
    rules.banned_job_ids = {"deadbeef"}
    rules.banned_companies = {normalize_company("Evil Inc")}
    rules.banned_years_regexes = [r"(\d+)\s*yrs?\b"]
    rules.banned_phrases = ["growth hacking"]
    rules.banned_title_keywords = ["ninja"]
    rules.banned_locations = ["remote (us)"]

    assert rules.check("deadbeef", "T", "C", "L", "D") is not None
    assert "EVIL INC" in rules.check("x", "T", "EVIL INC", "L", "D")
    assert "7 yrs" in rules.check("x", "T", "C", "L", "needs 7 yrs exp")
    assert "growth hacking" in rules.check("x", "T", "C", "L", "we do growth hacking")
    assert "ninja" in rules.check("x", "Code NINJA", "C", "L", "D")
    assert "remote (us)" in rules.check("x", "T", "C", "Remote (US)", "D")
    assert rules.check("ok", "Clean Title", "Fine Co", "Remote (India)",
                       "nothing wrong") is None


def test_normalize_company_strips_legal_suffixes():
    assert normalize_company("Acme Corp.") == normalize_company("acme inc")
    assert normalize_company("Acme LLC") == "acme"
