"""Tests for the failure-notification hook.

Seams under test:
  - scraper.notify.post_webhook(url, payload) -> bool   (real HTTP POST)
  - scraper.notify.notify_failure(cfg, summary) -> bool (fires only when
    the run had source failures and notifications are enabled)
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scraper.config import Config, NotificationsConfig
from scraper.notify import notify_failure, post_webhook


class _Collector(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _Collector.received.append({
            "path": self.path,
            "content_type": self.headers.get("Content-Type", ""),
            "payload": json.loads(body),
        })
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def webhook_server():
    server = HTTPServer(("127.0.0.1", 0), _Collector)
    _Collector.received = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/hook"
    server.shutdown()


def _cfg(webhook_url: str, enabled: bool = True) -> Config:
    return Config(
        notifications=NotificationsConfig(enabled=enabled, webhook_url=webhook_url)
    )


def _failing_summary():
    return {
        "mode": "daily",
        "sources_scraped": ["grepjob", "aijobs"],
        "failed_sources": ["aijobs"],
        "parsed_count": 3,
    }


def test_post_webhook_delivers_json_and_returns_true(webhook_server):
    assert post_webhook(webhook_server, {"hello": "world"}) is True
    assert len(_Collector.received) == 1
    r = _Collector.received[0]
    assert r["content_type"].startswith("application/json")
    assert r["payload"] == {"hello": "world"}


def test_post_webhook_returns_false_when_server_is_down():
    assert post_webhook("http://127.0.0.1:1/hook", {"a": 1}) is False


def test_notify_failure_posts_run_report_on_source_failures(webhook_server):
    sent = notify_failure(_cfg(webhook_server), _failing_summary())
    assert sent is True
    payload = _Collector.received[0]["payload"]
    assert payload["failed_sources"] == ["aijobs"]
    assert payload["mode"] == "daily"


def test_notify_failure_is_silent_on_healthy_runs(webhook_server):
    s = _failing_summary()
    s["failed_sources"] = []
    assert notify_failure(_cfg(webhook_server), s) is False
    assert _Collector.received == []


def test_notify_failure_respects_disabled_flag(webhook_server):
    assert notify_failure(_cfg(webhook_server, enabled=False), _failing_summary()) is False
    assert _Collector.received == []
