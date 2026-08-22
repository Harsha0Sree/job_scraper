"""
Shared utilities: logging, hashing, date parsing, atomic file writes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, date, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Optional, Union

import dateutil.parser as date_parser
from colorama import Fore, Style, init as colorama_init

colorama_init()


# --------------------------------------------------------------------------- #
#  Logging
# --------------------------------------------------------------------------- #

class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        record_msg = super().format(record)
        if sys.stderr.isatty():
            return f"{color}{record_msg}{Style.RESET_ALL}"
        return record_msg


def setup_logging(log_dir: Union[str, Path], verbose: bool = False) -> logging.Logger:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("scraper")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    file_handler = TimedRotatingFileHandler(
        log_dir / "scraper.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    console.setFormatter(
        ColorFormatter(
            fmt="%(asctime)s [%(levelname)-7s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(console)
    return logger


# --------------------------------------------------------------------------- #
#  Hashing / ID generation
# --------------------------------------------------------------------------- #

def job_id(url: str) -> str:
    """Stable 16-char ID derived from a job URL (used for dedup)."""
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return h[:16]


# --------------------------------------------------------------------------- #
#  Date parsing
# --------------------------------------------------------------------------- #

POSTED_RE = re.compile(r"posted\s+on\s+(.+?)\s*(?:\||<|$)", re.IGNORECASE)
AGO_RE = re.compile(r"(\d+)\s*(d|h|w|mo|y)\s*ago", re.IGNORECASE)


def parse_posted_date(text: str) -> Optional[date]:
    """Extract a date from 'Posted on Jul 31, 2026' or '9d ago' style strings."""
    if not text:
        return None
    m = POSTED_RE.search(text)
    if m:
        raw = m.group(1).strip().rstrip(".")
        try:
            return date_parser.parse(raw, fuzzy=False).date()
        except (ValueError, TypeError, date_parser.ParserError):
            pass
    # Try "9d ago", "3h ago", "2w ago"
    m = AGO_RE.search(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        today = date.today()
        if unit == "h":
            return today
        if unit == "d":
            return today - timedelta(days=n)
        if unit == "w":
            return today - timedelta(weeks=n)
        if unit == "mo":
            return today - timedelta(days=n * 30)
        if unit == "y":
            return today - timedelta(days=n * 365)
    # Try parsing the whole string as a date
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except (ValueError, TypeError, date_parser.ParserError):
        return None


def within_last_days(d: Optional[date], days: int, today: Optional[date] = None) -> bool:
    if d is None:
        return False
    today = today or date.today()
    return (today - d).days <= days and (today - d).days >= 0


# --------------------------------------------------------------------------- #
#  Atomic file writes
# --------------------------------------------------------------------------- #

def atomic_write_text(path: Union[str, Path], content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: Union[str, Path], obj: Any, indent: int = 2) -> None:
    atomic_write_text(path, json.dumps(obj, indent=indent, default=str, ensure_ascii=False))


# --------------------------------------------------------------------------- #
#  Misc
# --------------------------------------------------------------------------- #

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def truncate(text: str, n: int = 280) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def html_to_text(html: str) -> str:
    """Convert HTML to clean plain text, preserving paragraph breaks."""
    if not html:
        return ""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for br in soup.find_all(["br", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr"]):
        br.append("\n")
    text = soup.get_text(separator="", strip=False)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(lines).strip()
