"""Production-grade job scraper for backend/AI engineering remote/India roles.

Public API:
    from scraper import run_daily, run_range, run_source, load_config
    cfg = load_config()
    summary = run_daily(cfg)
"""
from .config import load_config, Config
from .pipeline import run_daily, run_range, run_source
from .data_model import ScrapedJob, RawJob
from .sources import get_adapter
from .ats import get_parser_for_url, JobDetail
from .filters import apply_filters, detect_location, detect_category, detect_zero_experience

__version__ = "3.0.0"

__all__ = [
    "load_config", "Config",
    "run_daily", "run_range", "run_source",
    "ScrapedJob", "RawJob",
    "get_adapter", "get_parser_for_url", "JobDetail",
    "apply_filters", "detect_location", "detect_category", "detect_zero_experience",
]
