"""
Job evaluation: turn a raw listing into a filtered, audited ScrapedJob.

This is the deep module behind the pipeline's per-job work. Its entire
interface is evaluate(): given a RawJob, a transport exposing Fetcher's
public get(), and the filter config, it performs ATS dispatch, field merge,
seniority extraction and filtering, recording every decision on the
returned ScrapedJob.
"""
from __future__ import annotations

import logging

from .config import FiltersConfig
from .data_model import RawJob, ScrapedJob
from .filters import apply_filters
from .ats import get_parser_for_url
from .utils import now_iso

log = logging.getLogger("scraper.evaluation")


def evaluate(raw: RawJob, fetcher, filters_cfg: FiltersConfig) -> ScrapedJob:
    """Evaluate one raw listing: deep-scrape its ATS page when it has one,
    then apply all three filters and record the outcome on the job."""
    job = ScrapedJob.from_raw(raw)
    job.scraped_at = now_iso()

    # Non-HTTP URLs are text-only listings (e.g. hnhiring://text/...):
    # filter on the listing hint without fetching.
    if not raw.ats_url.startswith("http"):
        job.description = raw.description_hint
        _apply_and_record(raw, job, filters_cfg)
        return job

    r = fetcher.get(raw.ats_url, use_cache=True)
    if not r.ok:
        job.error = f"fetch_failed status={r.status} err={r.error}"
        _log_decision(job)
        return job

    parser = get_parser_for_url(raw.ats_url)
    if parser is None:
        job.description = raw.description_hint
        _apply_and_record(raw, job, filters_cfg)
        return job

    detail = parser.parse(raw.ats_url, r.text)
    if detail.title:
        job.title = detail.title
    if detail.company:
        job.company = detail.company
    if detail.location:
        job.location = detail.location
    if detail.description:
        job.description = detail.description
    if detail.description_html:
        job.description_html = detail.description_html

    seniority = raw.seniority
    if detail.extra:
        for key in ("seniority", "level", "job_level", "seniority_level"):
            v = detail.extra.get(key, "")
            if v:
                seniority = str(v)
                break
    job.seniority = seniority

    _apply_and_record(raw, job, filters_cfg)
    return job


def _apply_and_record(raw: RawJob, job: ScrapedJob, cfg: FiltersConfig) -> None:
    fr = apply_filters(raw, job.title, job.description, job.location,
                       cfg, seniority_text=job.seniority)
    job.is_location_match = fr.is_location_match
    job.location_type = fr.location_type
    job.is_category_match = fr.is_category_match
    job.accepted = fr.accepted
    job.filter_reason = fr.reason
    job.category_signals = list(fr.category_signals)
    job.experience_signals = list(fr.experience_signals)
    job.years_mentioned = list(fr.years_mentioned)
    _log_decision(job)


def _log_decision(job: ScrapedJob) -> None:
    status = "ACCEPT" if job.accepted else "reject "
    if job.error:
        status = "ERROR  "
    loc = job.location_type or "—"
    log.info(
        "%s [%s] %s @ %s [%s] | loc=%s cat=%s exp=%s | %s",
        status,
        job.source,
        (job.title or "")[:50],
        (job.company or "")[:20],
        (job.location or "")[:30],
        loc,
        "Y" if job.is_category_match else "N",
        "Y" if job.accepted else "N",
        job.filter_reason[:80] if job.filter_reason else (job.error or "")[:80],
    )
