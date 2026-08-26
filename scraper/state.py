"""
State manager: persists seen-job IDs across runs to prevent duplicates.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .utils import atomic_write_json, now_iso
from .data_model import ScrapedJob

log = logging.getLogger("scraper.state")


class StateManager:
    def __init__(self, state_path: Path):
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state: Dict = self._load()

    def has(self, job_id: str) -> bool:
        return job_id in self._state.get("jobs", {})

    def mark_applied(self, job_id: str, ats_url: str, note: str = "") -> bool:
        """Record a user application. Returns True if newly recorded."""
        applied = self._state.setdefault("applied", {})
        if job_id in applied:
            return False
        applied[job_id] = {
            "applied_at": now_iso(),
            "ats_url": ats_url,
            "note": note,
        }
        return True

    def is_applied(self, job_id: str) -> bool:
        return job_id in self._state.get("applied", {})

    def applied_records(self) -> List[dict]:
        out = []
        for job_id, rec in self._state.get("applied", {}).items():
            seen = self._state.get("jobs", {}).get(job_id, {})
            out = out + [{
                "job_id": job_id,
                "applied_at": rec.get("applied_at", ""),
                "ats_url": rec.get("ats_url", ""),
                "note": rec.get("note", ""),
                "source": seen.get("source", ""),
                "title": seen.get("title", ""),
                "company": seen.get("company", ""),
                "location": seen.get("location", ""),
            }]
        return out

    def job_record(self, job_id: str) -> Optional[dict]:
        """Everything we know about a seen job (for feedback analysis)."""
        rec = self._state.get("jobs", {}).get(job_id)
        return dict(rec) if rec else None

    def mark_seen(self, jobs: List[ScrapedJob]) -> int:
        if "jobs" not in self._state:
            self._state["jobs"] = {}
        new_count = 0
        for job in jobs:
            entry = self._state["jobs"].get(job.job_id)
            now = now_iso()
            if entry is None:
                self._state["jobs"][job.job_id] = {
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "ats_url": job.ats_url,
                    "title": job.title,
                    "company": job.company,
                    "source": job.source,
                    "location": job.location,
                    "seniority": job.seniority,
                    "filter_reason": job.filter_reason,
                    # Bounded preview keeps feedback analysis possible offline
                    # without storing full descriptions.
                    "description_preview": (job.description_preview or "")[:500],
                }
                new_count += 1
            else:
                entry["last_seen_at"] = now
                for field in ("title", "company", "location", "seniority",
                              "filter_reason"):
                    if not entry.get(field) and getattr(job, field, ""):
                        entry[field] = getattr(job, field)
                if not entry.get("description_preview") and job.description_preview:
                    entry["description_preview"] = job.description_preview[:500]
        return new_count

    def save(self) -> None:
        self._state["last_run_at"] = now_iso()
        atomic_write_json(self.path, self._state)

    def stats(self) -> Dict:
        jobs = self._state.get("jobs", {})
        # Per-source breakdown
        by_source: Dict[str, int] = {}
        for j in jobs.values():
            s = j.get("source", "unknown")
            by_source[s] = by_source.get(s, 0) + 1
        return {
            "total_seen": len(jobs),
            "by_source": by_source,
            "last_run_at": self._state.get("last_run_at", ""),
            "state_path": str(self.path),
        }

    def _load(self) -> Dict:
        if not self.path.exists():
            return {"version": 1, "jobs": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            log.warning("state file corrupt, starting fresh: %s", e)
            backup = self.path.with_suffix(".json.bak")
            try:
                self.path.rename(backup)
            except OSError:
                pass
            return {"version": 1, "jobs": {}}
