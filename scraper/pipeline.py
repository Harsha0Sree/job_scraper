"""
Main scraping pipeline.

Pipeline:
    1. For each enabled source: fetch listings + parse job cards
    2. (optional) filter by posted_date within last N days
    3. For each job: fetch ATS detail page + parse
    4. Apply filters: location + category + zero-experience
    5. Persist to Excel + update state
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Dict, List, Optional

from .config import Config
from .fetcher import Fetcher
from .sources import get_adapter
from .evaluation import evaluate
from .data_model import RawJob, ScrapedJob
from .excel_writer import write_workbook
from .state import StateManager
from .utils import now_iso, within_last_days

log = logging.getLogger("scraper.pipeline")


def run_daily(cfg: Config) -> Dict:
    return _run_pipeline(cfg, mode="daily", days_back=None)


def run_range(cfg: Config, days: int) -> Dict:
    return _run_pipeline(cfg, mode=f"range-{days}d", days_back=days)


def run_source(cfg: Config, source_name: str, days_back: Optional[int] = None) -> Dict:
    return _run_pipeline(cfg, mode=f"source:{source_name}", days_back=days_back,
                         only_source=source_name)


def _run_pipeline(cfg: Config, mode: str, days_back: Optional[int],
                  only_source: Optional[str] = None) -> Dict:
    run_at = now_iso()
    started = time.monotonic()
    summary: Dict = {
        "run_at": run_at,
        "mode": mode,
        "days_back": days_back or "",
        "sources_scraped": [],
        "failed_sources": [],
        "by_source": {},
        "parsed_count": 0,
        "location_match_count": 0,
        "category_match_count": 0,
        "qualifying_count": 0,
        "not_location_count": 0,
        "wrong_category_count": 0,
        "has_experience_count": 0,
        "error_count": 0,
        "new_written": 0,
    }

    fetcher = Fetcher(cfg.http, cache_dir=cfg.project_root / "data" / "cache")

    # ---- 1. Fetch listings from each source ---------------------------- #
    sources = cfg.enabled_sources()
    if only_source:
        sources = [s for s in sources if s.name == only_source]
        if not sources:
            log.error("source '%s' not found in config", only_source)
            summary["duration_seconds"] = time.monotonic() - started
            return summary

    all_raw: List[RawJob] = []
    for sc in sources:
        try:
            adapter = get_adapter(sc, fetcher)
            log.info("=== fetching source: %s ===", sc.name)
            jobs = adapter.fetch_jobs()
            summary["sources_scraped"].append(sc.name)
            summary["by_source"][sc.name] = len(jobs)
            all_raw.extend(jobs)
        except Exception as e:
            log.exception("source %s failed: %s", sc.name, e)
            summary["sources_scraped"].append(sc.name)
            summary["failed_sources"].append(sc.name)
            summary["by_source"][sc.name] = 0
            summary["error_count"] += 1

    summary["parsed_count"] = len(all_raw)
    log.info("total raw jobs parsed: %d", len(all_raw))

    if not all_raw:
        summary["duration_seconds"] = time.monotonic() - started
        _save_summary(cfg, summary, [], [])
        return summary

    # Dedup raw jobs by ats_url (same job may appear on multiple pages)
    seen_urls: set = set()
    deduped_raw: List[RawJob] = []
    for r in all_raw:
        if r.ats_url in seen_urls:
            continue
        seen_urls.add(r.ats_url)
        deduped_raw.append(r)
    if len(deduped_raw) < len(all_raw):
        log.info("dedup: %d -> %d jobs (removed %d duplicates)",
                 len(all_raw), len(deduped_raw), len(all_raw) - len(deduped_raw))
    all_raw = deduped_raw

    # ---- 2. Date filter (range mode) ----------------------------------- #
    if days_back is not None:
        before = len(all_raw)
        all_raw = [
            j for j in all_raw
            if j.posted_date is None or within_last_days(j.posted_date, days_back)
        ]
        log.info("date filter (last %d days): %d -> %d jobs", days_back, before, len(all_raw))

    # ---- 3. Deep-scrape ATS detail pages ------------------------------- #
    scraped = _deep_scrape(all_raw, fetcher, cfg)

    # ---- 4. Apply filters (already applied in worker) ------------------ #
    # Now just tally up the results.
    qualifying: List[ScrapedJob] = []
    all_filtered: List[ScrapedJob] = []   # location OR category matched (audit)
    all_jobs: List[ScrapedJob] = []       # every scraped job (full audit)

    for job in scraped:
        all_jobs.append(job)
        if job.error:
            summary["error_count"] += 1
            continue
        if not job.is_location_match:
            summary["not_location_count"] += 1
            continue
        summary["location_match_count"] += 1
        if not job.is_category_match:
            summary["wrong_category_count"] += 1
            all_filtered.append(job)
            continue
        summary["category_match_count"] += 1
        all_filtered.append(job)
        if job.accepted:
            summary["qualifying_count"] += 1
            qualifying.append(job)
        else:
            summary["has_experience_count"] += 1

    # ---- 5. Persist ---------------------------------------------------- #
    state = StateManager(cfg.state_abspath())
    summary["new_written"] = state.mark_seen(qualifying)
    state.save()

    # Write Excel with ALL jobs for full audit trail
    _save_summary(cfg, summary, qualifying, all_filtered, all_jobs)

    summary["duration_seconds"] = time.monotonic() - started
    log.info(
        "run complete: parsed=%d loc_match=%d cat_match=%d qualifying=%d errors=%d duration=%.1fs",
        summary["parsed_count"], summary["location_match_count"],
        summary["category_match_count"], summary["qualifying_count"],
        summary["error_count"], summary["duration_seconds"],
    )

    # Log per-source qualifying counts
    by_source_qualified: Dict[str, int] = {}
    for j in qualifying:
        by_source_qualified[j.source] = by_source_qualified.get(j.source, 0) + 1
    if by_source_qualified:
        log.info("qualifying jobs by source: %s", by_source_qualified)

    return summary


def _deep_scrape(raws: List[RawJob], fetcher: Fetcher, cfg: Config) -> List[ScrapedJob]:
    results: List[ScrapedJob] = [None] * len(raws)  # type: ignore[list-item]
    show_progress = cfg.runtime.progress_bar

    def _worker(idx: int, raw: RawJob) -> ScrapedJob:
        try:
            return evaluate(raw, fetcher, cfg.filters)
        except Exception as e:
            job = ScrapedJob.from_raw(raw)
            job.scraped_at = now_iso()
            job.error = f"{type(e).__name__}: {e}"
            log.exception("error scraping %s", raw.ats_url)
            return job

    max_workers = max(1, cfg.runtime.max_workers)
    try:
        from tqdm import tqdm
        iter_wrapper = tqdm(total=len(raws), desc="Scraping", disable=not show_progress)
    except ImportError:
        iter_wrapper = None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_worker, i, r): i for i, r in enumerate(raws)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                log.error("worker crashed on %s: %s", raws[idx].ats_url, e)
                results[idx] = ScrapedJob.from_raw(raws[idx])
                results[idx].error = f"worker_crash: {e}"
            if iter_wrapper:
                iter_wrapper.update(1)

    if iter_wrapper:
        iter_wrapper.close()
    return [r for r in results if r is not None]


def _save_summary(cfg: Config, summary: Dict, qualifying: List[ScrapedJob],
                  all_filtered: List[ScrapedJob], all_jobs: List[ScrapedJob] = None) -> None:
    try:
        write_workbook(
            path=cfg.excel_abspath(),
            qualifying_jobs=qualifying,
            all_jobs=all_filtered,
            run_summary=summary,
            all_scraped_jobs=all_jobs or [],
        )
    except Exception as e:
        log.exception("excel write failed: %s", e)
