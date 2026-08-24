"""
Failure notifications: push a run report to a webhook when sources fail.

The hook is intentionally policy-light: it fires when a run had source
failures (summary["failed_sources"] non-empty) and notifications are
enabled in config. The scheduler-facing exit codes live in the CLI.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger("scraper.notify")


def post_webhook(url: str, payload: dict, timeout_seconds: int = 10) -> bool:
    """POST payload as JSON. Returns True on 2xx, False on any failure —
    notification problems must never crash the run itself."""
    try:
        resp = requests.post(url, json=payload, timeout=timeout_seconds)
        if 200 <= resp.status_code < 300:
            return True
        log.warning("webhook %s responded HTTP %s", url, resp.status_code)
        return False
    except requests.RequestException as e:
        log.warning("webhook %s failed: %s", url, e)
        return False


def notify_failure(cfg, summary: dict) -> bool:
    """Send a run report if the run had source failures and notifications
    are enabled. Returns True when a notification was sent."""
    n = cfg.notifications
    if not n.enabled or not n.webhook_url:
        return False
    failed = summary.get("failed_sources") or []
    if not failed:
        return False
    payload = {
        "event": "job_scraper_run_failed",
        "mode": summary.get("mode", ""),
        "run_at": summary.get("run_at", ""),
        "sources_scraped": summary.get("sources_scraped", []),
        "failed_sources": failed,
        "parsed_count": summary.get("parsed_count", 0),
        "error_count": summary.get("error_count", 0),
    }
    sent = post_webhook(n.webhook_url, payload, timeout_seconds=n.timeout_seconds)
    if sent:
        log.info("failure notification sent to webhook (%d failed sources)", len(failed))
    return sent
