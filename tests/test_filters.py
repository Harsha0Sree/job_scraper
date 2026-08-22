"""Tests for the filters module — location, category, zero-experience."""
from __future__ import annotations

import pytest

from scraper.config import (
    FiltersConfig, CategoryFilter, LocationFilter, ZeroExperienceFilter,
)
from scraper.filters import (
    detect_category, detect_location, detect_zero_experience, apply_filters,
)
from scraper.data_model import RawJob


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
                                        "work from anywhere", "fully remote",
                                        "remote (multiple locations)"],
            remote_india_patterns=["remote (india)", "remote, india"],
            india_locations=["bangalore", "mumbai", "delhi", "hyderabad", "pune",
                              "chennai", "bengaluru", "india"],
            restricted_remote_patterns=["remote (us)", "remote (europe)", "remote (uk)"],
            non_remote_non_india_patterns=[],
        ),
        zero_experience=ZeroExperienceFilter(
            senior_keywords=["senior", "lead", "principal", "staff", "manager", "director",
                              "architect", "expert"],
            seniority_levels_rejected=["senior-level", "mid-level"],
            min_years_threshold=1,
            min_years_patterns=[
                r"(\d+)\s*\+\s*years?",
                r"(\d+)\s*[-–to]{1,3}\s*\d+\s*years?",
                r"minimum\s+of\s+(\d+)\s+years?",
                r"at\s+least\s+(\d+)\s+years?",
                r"(\d+)\s+years?\s+of\s+experience",
                r"(\d+)\s+years?\s+experience",
            ],
            entry_level_signals=["entry level", "junior", "new grad", "internship",
                                  "fresher", "0 years", "0-1 years", "0-2 years",
                                  "no experience"],
            entry_level_seniority_levels=["entry level", "intern", "junior"],
            include_no_mention=False,
        ),
    )


# --------------------------- Category filter ------------------------------ #

def test_category_backend_title_match(cfg):
    ok, sig = detect_category("Backend Engineer", "Build APIs", cfg)
    assert ok is True
    assert any("backend" in s for s in sig)


def test_category_ai_title_match(cfg):
    ok, sig = detect_category("ML Engineer", "Train models", cfg)
    assert ok is True
    assert any("ai" in s or "ml" in s for s in sig)


def test_category_software_engineer_match(cfg):
    ok, sig = detect_category("Software Engineer", "Build stuff", cfg)
    assert ok is True


def test_category_exclude_frontend(cfg):
    ok, sig = detect_category("Frontend Engineer", "Build React UIs", cfg)
    assert ok is False
    assert "excluded:frontend" in sig[0]


def test_category_no_title_match(cfg):
    # "Operations Manager" has no backend/AI keyword in title
    ok, sig = detect_category("Operations Manager", "Run operations", cfg)
    assert ok is False
    assert sig == []


def test_category_desc_mention_doesnt_count(cfg):
    # Title is "Designer" but description mentions "backend API"
    # Should NOT match (title-focused)
    ok, sig = detect_category("Designer", "Work on our backend API", cfg)
    assert ok is False


# ----------------------------- Location filter ---------------------------- #

def test_location_remote_anywhere(cfg):
    ok, loc_type, reason = detect_location("Remote (Worldwide)", cfg)
    assert ok is True
    assert loc_type == "remote_anywhere"


def test_location_remote_india_explicit(cfg):
    ok, loc_type, reason = detect_location("Remote (India)", cfg)
    assert ok is True
    assert loc_type == "remote_india"


def test_location_remote_india_city(cfg):
    ok, loc_type, reason = detect_location("Remote, Bangalore", cfg)
    assert ok is True
    assert loc_type == "remote_india"


def test_location_onsite_india(cfg):
    ok, loc_type, reason = detect_location("Bengaluru, Karnataka", cfg)
    assert ok is True
    assert loc_type == "onsite_india"


def test_location_onsite_india_mumbai(cfg):
    ok, loc_type, reason = detect_location("Mumbai, India", cfg)
    assert ok is True
    assert loc_type == "onsite_india"


def test_location_restricted_us(cfg):
    ok, loc_type, reason = detect_location("Remote (US)", cfg)
    assert ok is False


def test_location_restricted_europe(cfg):
    ok, loc_type, reason = detect_location("Remote (Europe)", cfg)
    assert ok is False


def test_location_bare_remote_rejected(cfg):
    # Bare "Remote" with no qualifier should be REJECTED (ambiguous)
    ok, loc_type, reason = detect_location("Remote", cfg)
    assert ok is False


def test_location_no_location(cfg):
    ok, loc_type, reason = detect_location("", cfg)
    assert ok is False


def test_location_non_india_city(cfg):
    ok, loc_type, reason = detect_location("San Francisco, CA", cfg)
    assert ok is False


def test_location_london_rejected(cfg):
    ok, loc_type, reason = detect_location("London, UK", cfg)
    assert ok is False


def test_location_indonesia_not_india(cfg):
    # "Indonesia" contains "india" as substring — must NOT match
    ok, loc_type, reason = detect_location("Jakarta, Indonesia", cfg)
    assert ok is False
    assert "not remote, not india" in reason


def test_location_india_word_boundary(cfg):
    # "India" as a standalone word must match
    ok, loc_type, reason = detect_location("Bengaluru, India", cfg)
    assert ok is True
    assert loc_type == "onsite_india"


# ------------------------- Zero-experience filter ------------------------- #

def test_zero_exp_entry_level(cfg):
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "Entry level position", "", cfg)
    assert ok is True


def test_zero_exp_junior(cfg):
    ok, sig, yrs = detect_zero_experience("Junior Backend Engineer", "Build APIs", "", cfg)
    assert ok is True


def test_zero_exp_new_grad(cfg):
    ok, sig, yrs = detect_zero_experience("Software Engineer", "Open to new grads", "", cfg)
    assert ok is True


def test_zero_exp_internship(cfg):
    ok, sig, yrs = detect_zero_experience("Software Engineer Intern", "Summer internship", "", cfg)
    assert ok is True


def test_zero_exp_fresher(cfg):
    ok, sig, yrs = detect_zero_experience("Backend Developer", "Looking for freshers", "", cfg)
    assert ok is True


def test_zero_exp_rejected_senior_title(cfg):
    ok, sig, yrs = detect_zero_experience("Senior Backend Engineer", "No experience needed", "", cfg)
    assert ok is False


def test_zero_exp_rejected_mid_level_seniority(cfg):
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "Build APIs", "Mid-level", cfg)
    assert ok is False


def test_zero_exp_accept_entry_level_seniority(cfg):
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "Build APIs", "Entry level", cfg)
    assert ok is True


def test_zero_exp_rejected_years_plus(cfg):
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "3+ years of experience required", "", cfg)
    assert ok is False


def test_zero_exp_rejected_years_range(cfg):
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "2-4 years of experience", "", cfg)
    assert ok is False


def test_zero_exp_rejected_one_year_singular(cfg):
    # "1 year of experience" (singular, no +)
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "1 year of experience", "", cfg)
    assert ok is False


def test_zero_exp_rejected_2_years_no_of(cfg):
    # "2 years experience" (no "of")
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "2 years experience", "", cfg)
    assert ok is False


def test_zero_exp_accepts_0_to_2_years(cfg):
    # "0-2 years" should be ACCEPTED (entry-level range starting at 0)
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "0-2 years of experience", "", cfg)
    assert ok is True


def test_zero_exp_accepts_0_to_1_years(cfg):
    ok, sig, yrs = detect_zero_experience("Software Engineer", "0-1 years experience", "", cfg)
    assert ok is True


def test_zero_exp_no_signal_strict(cfg):
    ok, sig, yrs = detect_zero_experience("Backend Engineer", "Build great software.", "", cfg)
    assert ok is False


# --------------------------- Combined filter ------------------------------ #

def test_apply_filters_all_pass_remote_anywhere(cfg):
    raw = RawJob(
        source="test", title="Junior Backend Engineer",
        company="TestCo", location="Remote (Worldwide)",
        posted_date=None, ats_url="https://example.com/job/1",
    )
    fr = apply_filters(raw, "Junior Backend Engineer",
                       "Entry level position. Build APIs.",
                       "Remote (Worldwide)", cfg)
    assert fr.accepted is True
    assert fr.location_type == "remote_anywhere"


def test_apply_filters_onsite_india_passes(cfg):
    raw = RawJob(
        source="test", title="Software Engineer",
        company="TestCo", location="Bengaluru, India",
        posted_date=None, ats_url="https://example.com/job/2",
    )
    fr = apply_filters(raw, "Software Engineer",
                       "Entry level role. Build APIs.",
                       "Bengaluru, India", cfg)
    assert fr.accepted is True
    assert fr.location_type == "onsite_india"


def test_apply_filters_fails_location(cfg):
    raw = RawJob(
        source="test", title="Backend Engineer",
        company="TestCo", location="Remote (US)",
        posted_date=None, ats_url="https://example.com/job/3",
    )
    fr = apply_filters(raw, "Backend Engineer", "Build APIs", "Remote (US)", cfg)
    assert fr.accepted is False
    assert "location" in fr.reason.lower()


def test_apply_filters_fails_category(cfg):
    raw = RawJob(
        source="test", title="Frontend Engineer",
        company="TestCo", location="Remote (Worldwide)",
        posted_date=None, ats_url="https://example.com/job/4",
    )
    fr = apply_filters(raw, "Frontend Engineer", "Build React UIs",
                       "Remote (Worldwide)", cfg)
    assert fr.accepted is False
    assert "category" in fr.reason.lower()


def test_apply_filters_fails_experience(cfg):
    raw = RawJob(
        source="test", title="Backend Engineer",
        company="TestCo", location="Remote (Worldwide)",
        posted_date=None, ats_url="https://example.com/job/5",
    )
    fr = apply_filters(raw, "Backend Engineer",
                       "3+ years of experience building APIs",
                       "Remote (Worldwide)", cfg)
    assert fr.accepted is False
    assert "experience" in fr.reason.lower()


def test_apply_filters_bare_remote_rejected(cfg):
    raw = RawJob(
        source="test", title="Backend Engineer",
        company="TestCo", location="Remote",
        posted_date=None, ats_url="https://example.com/job/6",
    )
    fr = apply_filters(raw, "Backend Engineer", "Entry level", "Remote", cfg)
    assert fr.accepted is False
    assert "location" in fr.reason.lower()
