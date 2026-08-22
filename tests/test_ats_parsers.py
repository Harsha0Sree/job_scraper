"""Tests for the ATS parsers — uses saved HTML fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from scraper.ats import get_parser_for_url
from scraper.ats.greenhouse import GreenhouseParser
from scraper.ats.ashby import AshbyParser
from scraper.ats.aijobs_detail import AiJobsDetailParser
from scraper.ats.workatastartup_detail import WorkAtAStartupDetailParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_greenhouse_parser_basic():
    html = (FIXTURES / "greenhouse.html").read_text(encoding="utf-8")
    url = "https://job-boards.greenhouse.io/enterpret/jobs/7821474003"
    parser = GreenhouseParser()
    assert parser.can_parse(url) is True
    detail = parser.parse(url, html)
    assert detail.title, "title empty"
    assert detail.company, "company empty"
    assert detail.description, "description empty"
    assert len(detail.description) > 500
    assert detail.ats_provider == "greenhouse"


def test_ashby_parser_basic():
    html = (FIXTURES / "ashby.html").read_text(encoding="utf-8")
    url = "https://jobs.ashbyhq.com/base-power/780f2eea-c6a1-42ef-8b5a-244c411fe07b"
    parser = AshbyParser()
    assert parser.can_parse(url) is True
    detail = parser.parse(url, html)
    assert detail.title, "title empty"
    assert detail.company, "company empty"
    assert detail.description, "description empty"
    assert detail.ats_provider == "ashby"


def test_get_parser_dispatch():
    gh = get_parser_for_url("https://job-boards.greenhouse.io/x/jobs/1")
    assert isinstance(gh, GreenhouseParser)
    ashby = get_parser_for_url("https://jobs.ashbyhq.com/x/y")
    assert isinstance(ashby, AshbyParser)
    # WAS detail page
    was = get_parser_for_url("https://www.workatastartup.com/jobs/123")
    assert isinstance(was, WorkAtAStartupDetailParser)
    # aijobs detail page
    ai = get_parser_for_url("https://aijobs.net/job/some-slug-123/")
    assert isinstance(ai, AiJobsDetailParser)
    # Unknown host -> GenericParser
    from scraper.ats.generic import GenericParser
    g = get_parser_for_url("https://example.com/careers/1")
    assert isinstance(g, GenericParser)


def test_greenhouse_no_boilerplate_prefix():
    html = (FIXTURES / "greenhouse.html").read_text(encoding="utf-8")
    detail = GreenhouseParser().parse(
        "https://job-boards.greenhouse.io/x/jobs/1", html
    )
    assert not detail.description.startswith("Back to jobs")
