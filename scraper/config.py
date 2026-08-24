"""
Configuration loader.
Reads config.yaml and exposes a typed Config object.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml


# --------------------------------------------------------------------------- #
#  Typed config dataclasses
# --------------------------------------------------------------------------- #

@dataclass
class SourceConfig:
    name: str
    enabled: bool = True
    adapter: str = ""
    url: str = ""
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CategoryFilter:
    backend_title_keywords: List[str] = field(default_factory=list)
    ai_title_keywords: List[str] = field(default_factory=list)
    exclude_title_keywords: List[str] = field(default_factory=list)


@dataclass
class LocationFilter:
    remote_anywhere_patterns: List[str] = field(default_factory=list)
    remote_india_patterns: List[str] = field(default_factory=list)
    india_locations: List[str] = field(default_factory=list)
    restricted_remote_patterns: List[str] = field(default_factory=list)
    non_remote_non_india_patterns: List[str] = field(default_factory=list)


@dataclass
class ZeroExperienceFilter:
    senior_keywords: List[str] = field(default_factory=list)
    seniority_levels_rejected: List[str] = field(default_factory=list)
    min_years_threshold: int = 1
    min_years_patterns: List[str] = field(default_factory=list)
    entry_level_signals: List[str] = field(default_factory=list)
    entry_level_seniority_levels: List[str] = field(default_factory=list)
    include_no_mention: bool = False


@dataclass
class FiltersConfig:
    category: CategoryFilter = field(default_factory=CategoryFilter)
    location: LocationFilter = field(default_factory=LocationFilter)
    zero_experience: ZeroExperienceFilter = field(default_factory=ZeroExperienceFilter)


@dataclass
class HttpConfig:
    per_host_delay_seconds: float = 2.0
    jitter_seconds: float = 1.0
    timeout_seconds: int = 30
    max_retries: int = 3
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    cache_ttl_hours: int = 24


@dataclass
class OutputConfig:
    excel_path: str = "jobs_zero_experience.xlsx"
    state_path: str = "data/state.json"
    log_dir: str = "data/logs"


@dataclass
class RuntimeConfig:
    max_workers: int = 4
    progress_bar: bool = True
    verbose: bool = True


@dataclass
class NotificationsConfig:
    enabled: bool = False
    webhook_url: str = ""
    timeout_seconds: int = 10


@dataclass
class Config:
    sources: List[SourceConfig] = field(default_factory=list)
    filters: FiltersConfig = field(default_factory=FiltersConfig)
    http: HttpConfig = field(default_factory=HttpConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    project_root: Path = Path.cwd()

    def excel_abspath(self) -> Path:
        p = Path(self.output.excel_path)
        return p if p.is_absolute() else self.project_root / p

    def state_abspath(self) -> Path:
        p = Path(self.output.state_path)
        return p if p.is_absolute() else self.project_root / p

    def log_dir_abspath(self) -> Path:
        p = Path(self.output.log_dir)
        return p if p.is_absolute() else self.project_root / p

    def enabled_sources(self) -> List[SourceConfig]:
        return [s for s in self.sources if s.enabled]


# --------------------------------------------------------------------------- #
#  Loader
# --------------------------------------------------------------------------- #

_DEFAULTS: Dict[str, Any] = {
    "sources": {},
    "filters": {
        "category": {
            "backend_title_keywords": ["backend", "software engineer"],
            "ai_title_keywords": ["ai engineer", "ml engineer"],
            "exclude_title_keywords": ["frontend", "mobile", "designer"],
        },
        "location": {
            "remote_anywhere_patterns": ["remote (worldwide)", "work from anywhere"],
            "remote_india_patterns": ["remote (india)"],
            "india_locations": ["bangalore", "mumbai", "delhi", "hyderabad", "pune", "chennai"],
            "restricted_remote_patterns": ["remote (us)", "remote (europe)"],
            "non_remote_non_india_patterns": [],
        },
        "zero_experience": {
            "senior_keywords": ["senior", "lead", "principal", "staff"],
            "seniority_levels_rejected": ["senior-level", "mid-level"],
            "min_years_threshold": 1,
            "min_years_patterns": [r"(\d+)\s*\+\s*years?"],
            "entry_level_signals": ["entry level", "junior", "new grad", "internship"],
            "entry_level_seniority_levels": ["entry level", "intern", "junior"],
            "include_no_mention": False,
        },
    },
    "http": {
        "per_host_delay_seconds": 2.0,
        "jitter_seconds": 1.0,
        "timeout_seconds": 30,
        "max_retries": 3,
        "backoff_base_seconds": 2.0,
        "backoff_max_seconds": 60.0,
        "cache_ttl_hours": 24,
    },
    "output": {
        "excel_path": "jobs_zero_experience.xlsx",
        "state_path": "data/state.json",
        "log_dir": "data/logs",
    },
    "runtime": {"max_workers": 4, "progress_bar": True, "verbose": True},
    "notifications": {"enabled": False, "webhook_url": "", "timeout_seconds": 10},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(config_path: str | Path | None = None) -> Config:
    if config_path is None:
        env_path = os.environ.get("JOB_SCRAPER_CONFIG")
        if env_path and Path(env_path).exists():
            config_path = Path(env_path)
        else:
            here = Path(__file__).resolve().parent.parent
            config_path = here / "config.yaml"
            if not config_path.exists():
                config_path = Path.cwd() / "config.yaml"

    config_path = Path(config_path).resolve()
    project_root = config_path.parent

    raw: Dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    merged = _deep_merge(_DEFAULTS, raw)

    # Sources
    sources: List[SourceConfig] = []
    for name, sraw in (merged.get("sources") or {}).items():
        sources.append(
            SourceConfig(
                name=name,
                enabled=sraw.get("enabled", True),
                adapter=sraw.get("adapter", name),
                url=sraw.get("url", ""),
                options={k: v for k, v in sraw.items()
                         if k not in {"enabled", "adapter", "url"}},
            )
        )

    # Filters
    f = merged["filters"]
    cat = f.get("category", {})
    loc = f.get("location", {})
    ze = f.get("zero_experience", {})

    filters = FiltersConfig(
        category=CategoryFilter(
            backend_title_keywords=cat.get("backend_title_keywords", []),
            ai_title_keywords=cat.get("ai_title_keywords", []),
            exclude_title_keywords=cat.get("exclude_title_keywords", []),
        ),
        location=LocationFilter(
            remote_anywhere_patterns=loc.get("remote_anywhere_patterns", []),
            remote_india_patterns=loc.get("remote_india_patterns", []),
            india_locations=loc.get("india_locations", []),
            restricted_remote_patterns=loc.get("restricted_remote_patterns", []),
            non_remote_non_india_patterns=loc.get("non_remote_non_india_patterns", []),
        ),
        zero_experience=ZeroExperienceFilter(
            senior_keywords=ze.get("senior_keywords", []),
            seniority_levels_rejected=ze.get("seniority_levels_rejected", []),
            min_years_threshold=ze.get("min_years_threshold", 1),
            min_years_patterns=ze.get("min_years_patterns", []),
            entry_level_signals=ze.get("entry_level_signals", []),
            entry_level_seniority_levels=ze.get("entry_level_seniority_levels", []),
            include_no_mention=ze.get("include_no_mention", False),
        ),
    )

    http = HttpConfig(**merged["http"])
    out = OutputConfig(**merged["output"])
    rt = RuntimeConfig(**merged["runtime"])
    notifications = NotificationsConfig(**merged["notifications"])

    return Config(
        sources=sources,
        filters=filters,
        http=http,
        output=out,
        runtime=rt,
        notifications=notifications,
        project_root=project_root,
    )
