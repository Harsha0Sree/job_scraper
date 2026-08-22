"""
wellfound.com source adapter.

⚠️ Wellfound is behind DataDome anti-bot protection. Direct HTTP requests
return HTTP 403 with a "Please enable JS" message. This adapter handles
that gracefully:

  1. Try a direct HTTP fetch first.
  2. If we get a 403 with "datadome" or "Please enable JS", log a warning
     and return an empty list (with guidance on how to enable it).
  3. If use_browser: true is set in config AND playwright is installed,
     use a headless browser to fetch the page.

To enable browser-based fetching:
    uv pip install playwright
    playwright install chromium
    # Then set use_browser: true in config.yaml under sources.wellfound
"""
from __future__ import annotations

import logging
import re
from typing import List

from bs4 import BeautifulSoup

from ..data_model import RawJob
from .base import SourceAdapter, register_adapter

log = logging.getLogger("scraper.sources.wellfound")


@register_adapter
class WellfoundAdapter(SourceAdapter):
    name = "wellfound"

    def fetch_jobs(self) -> List[RawJob]:
        url = self.cfg.url
        use_browser = bool(self.cfg.options.get("use_browser", False))
        log.info("[%s] fetching %s (use_browser=%s)", self.name, url, use_browser)

        if use_browser:
            html = self._fetch_with_browser(url)
            if html:
                return self._parse(html)
            return []

        # Direct HTTP fetch
        r = self.fetcher.get(url, use_cache=False)
        if not r.ok:
            if r.status == 403 and ("datadome" in r.text.lower() or "enable js" in r.text.lower()):
                log.warning(
                    "[%s] BLOCKED by DataDome anti-bot protection. "
                    "To enable scraping, install playwright and set "
                    "'use_browser: true' in config.yaml under sources.wellfound. "
                    "Skipping this source.", self.name
                )
            else:
                log.warning("[%s] fetch failed: status=%s err=%s", self.name, r.status, r.error)
            return []
        return self._parse(r.text)

    def _fetch_with_browser(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error(
                "[%s] use_browser=true but playwright is not installed. "
                "Run: uv pip install playwright && playwright install chromium",
                self.name,
            )
            return ""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                )
                page = ctx.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                # Wait for job cards to render
                try:
                    page.wait_for_selector("[class*='job'], [class*='posting']", timeout=10000)
                except Exception:
                    pass
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            log.error("[%s] browser fetch failed: %s", self.name, e)
            return ""

    def _parse(self, html: str) -> List[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: List[RawJob] = []
        # Wellfound's job cards have specific structures that change often.
        # Look for anchors with /jobs/<id> pattern
        for a in soup.find_all("a", href=re.compile(r"^/jobs/\d+")):
            try:
                job = self._parse_card(a)
                if job:
                    jobs.append(job)
            except Exception as e:
                log.debug("error parsing wellfound card: %s", e)
        log.info("[%s] parsed %d jobs", self.name, len(jobs))
        return jobs

    def _parse_card(self, a):
        href = a["href"]
        ats_url = f"https://wellfound.com{href}"
        title = a.get_text(" ", strip=True)
        if not title or len(title) > 200:
            return None
        # Walk up to find the card container
        card = a
        for _ in range(6):
            card = card.parent
            if card is None: break
            cls = " ".join(card.get("class", [])) if card.get("class") else ""
            if "job" in cls.lower() or "posting" in cls.lower() or "result" in cls.lower():
                break
        # Try to extract company and location from the card
        company = ""
        location = ""
        if card:
            text = card.get_text(" | ", strip=True)
            # Heuristic: split on | and look for company/location patterns
            parts = [p.strip() for p in text.split("|") if p.strip()]
            for p in parts[1:]:  # skip title
                if not company and len(p) < 60 and not any(c.isdigit() for c in p):
                    company = p
                elif not location and ("," in p or "remote" in p.lower()):
                    location = p
        return RawJob(
            source=self.name,
            title=title,
            company=company,
            location=location,
            posted_date=None,
            ats_url=ats_url,
            ats_provider="wellfound",
            description_hint="",
        )
