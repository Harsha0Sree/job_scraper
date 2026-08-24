"""
ATS provider registry: the single owner of URL -> provider labels.

Adapters that scrape multi-ATS apply links (grepjob, hnhiring, no-wb,
startups.gallery) label their jobs through detect_provider(). Single-board
sources (aijobs, workatastartup, wellfound) may self-label with their own
name. The ATS dispatch in scraper.ats.base is expected to agree with this
registry for every URL it dispatches (pinned by tests/test_providers.py).
Adding a new ATS means adding one entry here plus a parser registered
against the same provider name.
"""
from __future__ import annotations

# Substring match on the lowercased URL. Order matters only where one
# entry is more specific than another (e.g. linkedin job URLs).
_HOST_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("linkedin.com/jobs", "linkedin"),
    ("job-boards.greenhouse.io", "greenhouse"),
    ("boards.greenhouse.io", "greenhouse"),
    ("greenhouse.io", "greenhouse"),
    ("ashbyhq.com", "ashby"),
    ("lever.co", "lever"),
    ("workable.com", "workable"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("rippling.com", "rippling"),
    ("tally.so", "tally"),
    ("aijobs.net", "aijobs"),
    ("workatastartup.com", "workatastartup"),
    ("grepjob.com", "grepjob"),
)


def detect_provider(url: str) -> str:
    """Return the ATS provider name for a URL ('generic' if unknown)."""
    u = (url or "").lower()
    for host, provider in _HOST_PROVIDERS:
        if host in u:
            return provider
    return "generic"


def hosts_for(provider: str) -> tuple[str, ...]:
    """All registered host patterns that label as `provider`.

    ATS parsers must draw their dispatch hosts from here instead of
    restating literals, so a URL's provider label can never disagree
    with the parser dispatched for it.
    """
    return tuple(h for h, p in _HOST_PROVIDERS if p == provider)
