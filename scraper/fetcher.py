"""
HTTP fetcher with per-host rate limiting, retries, disk cache, and
realistic rotating User-Agent strings.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from fake_useragent import UserAgent
    _UA = UserAgent()
    def _random_ua() -> str:
        try:
            return _UA.random
        except Exception:
            return _FALLBACK_UA
except Exception:
    _UA = None
    def _random_ua() -> str:
        return random.choice(_FALLBACK_UAS)


_FALLBACK_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_FALLBACK_UAS = [
    _FALLBACK_UA,
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

log = logging.getLogger("scraper.fetcher")


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    from_cache: bool = False
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300


class Fetcher:
    def __init__(self, http_cfg, cache_dir: Optional[Path] = None):
        self.cfg = http_cfg
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._host_locks: Dict[str, Lock] = {}
        self._host_last_request: Dict[str, float] = {}
        self._global_lock = Lock()

        self.session = requests.Session()
        retry = Retry(
            total=self.cfg.max_retries,
            connect=self.cfg.max_retries,
            read=self.cfg.max_retries,
            status=0,
            backoff_factor=self.cfg.backoff_base_seconds,
            status_forcelist=[],
            allowed_methods=frozenset(["GET", "HEAD"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get(self, url: str, use_cache: bool = True, headers: Optional[Dict] = None) -> FetchResult:
        if use_cache and self.cache_dir:
            cached = self._cache_get(url)
            if cached is not None:
                log.debug("cache hit: %s", url)
                return FetchResult(
                    url=url,
                    status=cached.get("status", 200),
                    text=cached.get("text", ""),
                    from_cache=True,
                )

        host = urlparse(url).netloc
        self._wait_for_host(host)

        result = self._fetch_with_retries(url, extra_headers=headers)
        if result.ok and use_cache and self.cache_dir:
            self._cache_put(url, result)
        return result

    def _wait_for_host(self, host: str) -> None:
        with self._global_lock:
            lock = self._host_locks.setdefault(host, Lock())
        with lock:
            now = time.monotonic()
            last = self._host_last_request.get(host, 0.0)
            delay = self.cfg.per_host_delay_seconds + random.uniform(
                0, self.cfg.jitter_seconds
            )
            wait_for = (last + delay) - now
            if wait_for > 0:
                log.debug("host %s: sleeping %.2fs", host, wait_for)
                time.sleep(wait_for)
            self._host_last_request[host] = time.monotonic()

    def _fetch_with_retries(self, url: str, extra_headers: Optional[Dict] = None) -> FetchResult:
        last_err: Optional[str] = None
        start = time.monotonic()
        for attempt in range(self.cfg.max_retries + 1):
            headers = self._headers()
            if extra_headers:
                headers.update(extra_headers)
            try:
                resp = self.session.get(
                    url,
                    headers=headers,
                    timeout=self.cfg.timeout_seconds,
                    allow_redirects=True,
                )
                # Fix charset: HTTP spec defaults to ISO-8859-1 when no charset
                # is declared, but modern HTML is almost always UTF-8.
                ctype = resp.headers.get("Content-Type", "").lower()
                if "charset=" not in ctype:
                    try:
                        resp.encoding = "utf-8"
                    except Exception:
                        pass

                elapsed = time.monotonic() - start
                if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                    last_err = f"HTTP {resp.status_code}"
                    if attempt < self.cfg.max_retries:
                        backoff = min(
                            self.cfg.backoff_max_seconds,
                            self.cfg.backoff_base_seconds * (2 ** attempt),
                        )
                        log.warning(
                            "fetch %s -> %s; retry %d/%d after %.1fs",
                            url, resp.status_code, attempt + 1, self.cfg.max_retries, backoff,
                        )
                        time.sleep(backoff)
                        continue
                    return FetchResult(
                        url=url, status=resp.status_code, text=resp.text,
                        elapsed_seconds=elapsed, error=last_err,
                    )
                return FetchResult(
                    url=url, status=resp.status_code, text=resp.text,
                    elapsed_seconds=elapsed,
                )
            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < self.cfg.max_retries:
                    backoff = min(
                        self.cfg.backoff_max_seconds,
                        self.cfg.backoff_base_seconds * (2 ** attempt),
                    )
                    log.warning(
                        "fetch %s error: %s; retry %d/%d after %.1fs",
                        url, last_err, attempt + 1, self.cfg.max_retries, backoff,
                    )
                    time.sleep(backoff)
                    continue
        return FetchResult(url=url, status=0, text="", error=last_err or "unknown")

    def _headers(self) -> Dict[str, str]:
        # Let requests handle Accept-Encoding itself — it advertises only
        # the encodings it can decode (gzip, deflate, brotli if installed).
        return {
            "User-Agent": _random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }

    def _cache_key(self, url: str) -> Path:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{h}.json"  # type: ignore[union-attr]

    def _cache_get(self, url: str) -> Optional[dict]:
        path = self._cache_key(url)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(data["cached_at"])
            ttl = timedelta(hours=self.cfg.cache_ttl_hours)
            if datetime.now() - ts > ttl:
                return None
            return data
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def _cache_put(self, url: str, result: FetchResult) -> None:
        path = self._cache_key(url)
        data = {
            "url": url,
            "status": result.status,
            "text": result.text,
            "cached_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            log.debug("cache write failed: %s", e)
