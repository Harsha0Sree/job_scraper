"""Tests for the ATS provider registry: one owner of URL -> provider labels.

The seam under test is scraper.providers.detect_provider(url). The
consistency test pins the contract that the provider label recorded in
output always equals the parser actually dispatched for that URL.
"""
from __future__ import annotations

import pytest

from scraper.ats.base import get_parser_for_url, _REGISTRY
from scraper.providers import detect_provider, hosts_for


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse"),
    ("https://jobs.ashbyhq.com/acme/abc", "ashby"),
    ("https://jobs.lever.co/acme/abc-def", "lever"),
    ("https://acme.workable.com/j/123", "workable"),
    ("https://jobs.smartrecruiters.com/Acme/123", "smartrecruiters"),
    ("https://acme.rippling.com/en-US/jobs/abc", "rippling"),
    ("https://tally.so/r/abc", "tally"),
    ("https://www.linkedin.com/jobs/view/123", "linkedin"),
    ("https://aijobs.net/job/12345", "aijobs"),
    ("https://www.workatastartup.com/jobs/123", "workatastartup"),
    ("https://grepjob.com/jobs/uuid", "grepjob"),
])
def test_known_ats_hosts_map_to_their_provider(url, expected):
    assert detect_provider(url) == expected


def test_unknown_url_falls_back_to_generic():
    assert detect_provider("https://careers.example.com/listing/9") == "generic"


@pytest.mark.parametrize("url", [
    "https://boards.greenhouse.io/enterpret/jobs/7821474003",
    "https://jobs.ashbyhq.com/enterpret/abc",
    "https://jobs.lever.co/acme/abc",
    "https://aijobs.net/job/12345",
    "https://www.workatastartup.com/jobs/5748392",
])
def test_provider_label_always_matches_dispatched_parser(url):
    parser = get_parser_for_url(url)
    assert parser is not None, f"no parser dispatched for {url}"
    assert detect_provider(url) == parser.provider


def test_every_specific_parser_draws_its_hosts_from_the_provider_registry():
    """Single source of truth: a parser's dispatch hosts must BE the
    registry's hosts for its provider, so label and dispatch can never
    drift apart."""
    specific = [cls for cls in _REGISTRY if not getattr(cls, "is_fallback", False)]
    assert len(specific) == 5  # greenhouse, ashby, lever, aijobs, workatastartup

    for cls in specific:
        assert cls.url_hosts, f"{cls.__name__} must declare url_hosts"
        assert cls.provider != "generic"
        assert tuple(cls.url_hosts) == tuple(hosts_for(cls.provider)), (
            f"{cls.__name__} hosts drift from the provider registry"
        )
