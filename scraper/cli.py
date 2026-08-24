"""
Command-line interface.

Usage:
    uv run python -m scraper.cli daily                    # Scrape today's jobs (all sources)
    uv run python -m scraper.cli range --days 7           # Last 7 days
    uv run python -m scraper.cli range --days 30          # Last 30 days
    uv run python -m scraper.cli source hnhiring          # Scrape only one source
    uv run python -m scraper.cli source hnhiring --days 7 # One source, last 7 days
    uv run python -m scraper.cli status                   # Show state stats
    uv run python -m scraper.cli list-sources             # List all configured sources
    uv run python -m scraper.cli test                     # Smoke test (listings only)
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

from .config import load_config
from .utils import setup_logging
from .pipeline import run_daily, run_range, run_source
from .state import StateManager
from .notify import notify_failure


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scraper",
        description="Production-grade remote backend/AI job scraper (7 sources)",
    )
    p.add_argument("--config", "-c", help="Path to config.yaml", default=None)
    p.add_argument("--verbose", "-v", help="Verbose (DEBUG) logging", action="store_true")
    p.add_argument("--quiet", "-q", help="Quiet mode (warnings only)", action="store_true")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("daily", help="Run the daily scrape across all enabled sources")

    rng = sub.add_parser("range", help="Scrape jobs posted within last N days")
    rng.add_argument("--days", "-d", type=int, required=True,
                     help="Number of days back to include (e.g. 7, 30)")

    src = sub.add_parser("source", help="Scrape only one source (by name)")
    src.add_argument("name", help="Source name from config.yaml (e.g. hnhiring, no_wb)")
    src.add_argument("--days", "-d", type=int, default=None,
                     help="Optional: only jobs from last N days")

    sub.add_parser("status", help="Show stats from state.json")
    sub.add_parser("list-sources", help="List all configured sources")
    sub.add_parser("test", help="Smoke test: fetch listings from all sources, no ATS deep-scrape")
    return p


def resolve_exit_code(summary: dict) -> int:
    """Translate a run summary into the scheduler-facing exit code.

    0  ok
    1  nothing parsed, but no source errors (a quiet day)
    3  partial failure: at least one source errored
    4  total failure: every scraped source errored
    """
    failed = summary.get("failed_sources") or []
    scraped = summary.get("sources_scraped") or []
    if failed and len(failed) >= len(scraped):
        return 4
    if failed:
        return 3
    return 0 if summary.get("parsed_count", 0) > 0 else 1


def render_summary(summary: dict) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  Run mode:           {summary.get('mode', '')}")
    lines.append(f"  Sources scraped:    {', '.join(summary.get('sources_scraped', []))}")
    failed = summary.get("failed_sources") or []
    if failed:
        lines.append(f"  Failed sources:     {', '.join(failed)}")
    lines.append(f"  Total parsed:       {summary.get('parsed_count', 0)}")
    lines.append(f"  Location matches:   {summary.get('location_match_count', 0)}")
    lines.append(f"  Category matches:   {summary.get('category_match_count', 0)}")
    lines.append(f"  Qualifying (0 yrs): {summary.get('qualifying_count', 0)}")
    lines.append(f"  Rejected (location):  {summary.get('not_location_count', 0)}")
    lines.append(f"  Wrong category:     {summary.get('wrong_category_count', 0)}")
    lines.append(f"  Has experience:     {summary.get('has_experience_count', 0)}")
    lines.append(f"  Errors:             {summary.get('error_count', 0)}")
    lines.append(f"  Newly written:      {summary.get('new_written', 0)}")
    lines.append(f"  Duration:           {summary.get('duration_seconds', 0):.1f}s")
    lines.append("")
    lines.append("  Per-source breakdown:")
    for src, n in sorted(summary.get("by_source", {}).items()):
        lines.append(f"    {src}: {n} jobs")
    lines.append("=" * 70)
    lines.append("")
    return "\n".join(lines)


def _finish_run(cfg, summary: dict) -> int:
    notify_failure(cfg, summary)
    return resolve_exit_code(summary)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"ERROR: could not load config: {e}", file=sys.stderr)
        return 2

    verbose = args.verbose or cfg.runtime.verbose
    setup_logging(cfg.log_dir_abspath(), verbose=verbose)
    log = logging.getLogger("scraper.cli")
    log.info("==== scraper start: %s ====", args.command)

    try:
        if args.command == "daily":
            summary = run_daily(cfg)
            print(render_summary(summary))
            return _finish_run(cfg, summary)

        elif args.command == "range":
            if args.days < 1:
                print("ERROR: --days must be >= 1", file=sys.stderr)
                return 2
            summary = run_range(cfg, args.days)
            print(render_summary(summary))
            return _finish_run(cfg, summary)

        elif args.command == "source":
            summary = run_source(cfg, args.name, days_back=args.days)
            print(render_summary(summary))
            return _finish_run(cfg, summary)

        elif args.command == "status":
            state = StateManager(cfg.state_abspath())
            stats = state.stats()
            print("=== Scraper State ===")
            for k, v in stats.items():
                if k == "by_source":
                    print(f"  by_source:")
                    for src, n in sorted(v.items()):
                        print(f"    {src}: {n}")
                else:
                    print(f"  {k}: {v}")
            return 0

        elif args.command == "list-sources":
            print("=== Configured sources ===")
            for s in cfg.sources:
                status = "ENABLED" if s.enabled else "DISABLED"
                print(f"  [{status}] {s.name} (adapter={s.adapter})")
                print(f"           URL: {s.url}")
                if s.options:
                    print(f"           Options: {s.options}")
            return 0

        elif args.command == "test":
            return _smoke_test(cfg)

        else:
            print(f"ERROR: unknown command {args.command}", file=sys.stderr)
            return 2

    except KeyboardInterrupt:
        log.warning("interrupted by user")
        return 1
    except Exception as e:
        log.error("fatal error: %s", e)
        log.debug("traceback:\n%s", traceback.format_exc())
        return 2


def _smoke_test(cfg) -> int:
    """Quick smoke test: fetch listings from each source, print first 3 jobs."""
    from .fetcher import Fetcher
    from .sources import get_adapter

    fetcher = Fetcher(cfg.http, cache_dir=cfg.project_root / "data" / "cache")
    total = 0
    for sc in cfg.enabled_sources():
        print(f"\n=== Source: {sc.name} ===")
        print(f"  URL: {sc.url}")
        try:
            adapter = get_adapter(sc, fetcher)
            jobs = adapter.fetch_jobs()
            print(f"  Parsed: {len(jobs)} jobs")
            for j in jobs[:3]:
                print(f"    - {j.title[:60]} @ {j.company} [{j.location}]")
                print(f"      URL: {j.ats_url[:80]}")
            if len(jobs) > 3:
                print(f"    ... ({len(jobs) - 3} more)")
            total += len(jobs)
        except Exception as e:
            print(f"  ERROR: {e}")
    print(f"\nTotal jobs across all sources: {total}")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
