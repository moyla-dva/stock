"""Background jobs for refreshing local stock concept metadata."""

import concurrent.futures
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path


TERMINAL_STATUSES = {"completed", "failed", "interrupted"}
DEFAULT_HISTORY_PATH = Path(os.environ.get(
    "STOCK_ANALYZER_CONCEPT_JOB_HISTORY_PATH",
    Path(__file__).resolve().parents[1] / ".cache" / "concept_jobs" / "jobs.json",
))


def _now_text():
    return datetime.now().isoformat(timespec="seconds")


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class ConceptRefreshJobManager:
    def __init__(self, max_workers=1, history_path=DEFAULT_HISTORY_PATH, max_history=20):
        self.history_path = Path(history_path) if history_path else None
        self.max_history = max_history
        self._lock = threading.Lock()
        self._jobs = {}
        self._job_futures = {}
        self._load_history()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def start_job(self, refresh_func, max_concepts=None):
        active = self.current_job()
        if active and active.get("status") not in TERMINAL_STATUSES:
            return active

        job_id = uuid.uuid4().hex[:12]
        now = _now_text()
        job = {
            "id": job_id,
            "status": "queued",
            "total": 0,
            "completed": 0,
            "progress": 0,
            "current_concept": "",
            "stock_count": 0,
            "concept_count": 0,
            "max_concepts": max_concepts,
            "error": None,
            "created_at": now,
            "started_at": None,
            "updated_at": now,
            "finished_at": None,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._persist_jobs_unlocked()

        future = self._executor.submit(self._run_job, job_id, refresh_func, max_concepts)
        with self._lock:
            self._job_futures[job_id] = future
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return self._copy_job(job)

    def current_job(self):
        with self._lock:
            if not self._jobs:
                return None
            job = sorted(
                self._jobs.values(),
                key=lambda item: item.get("created_at") or "",
                reverse=True,
            )[0]
            return self._copy_job(job)

    def list_jobs(self, limit=20):
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda item: item.get("created_at") or "",
                reverse=True,
            )
            return [self._copy_job(job) for job in jobs[:limit]]

    def shutdown(self, wait=True):
        self._executor.shutdown(wait=wait)

    def _copy_job(self, job):
        copy = dict(job)
        copy["duration_seconds"] = self._duration_seconds(job)
        return copy

    def _duration_seconds(self, job):
        started = _parse_time(job.get("started_at")) or _parse_time(job.get("created_at"))
        finished = _parse_time(job.get("finished_at"))
        if started is None:
            return None
        if finished is None and job.get("status") not in TERMINAL_STATUSES:
            finished = datetime.now()
        if finished is None:
            finished = _parse_time(job.get("updated_at"))
        if finished is None:
            return None
        return max(0, int((finished - started).total_seconds()))

    def _update_job(self, job_id, **updates):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.update(updates)
            total = int(job.get("total") or 0)
            completed = int(job.get("completed") or 0)
            job["progress"] = 100 if total == 0 and job.get("status") == "completed" else (
                int((completed / total) * 100) if total else 0
            )
            job["updated_at"] = _now_text()
            self._persist_jobs_unlocked()
            return self._copy_job(job)

    def _run_job(self, job_id, refresh_func, max_concepts):
        self._update_job(job_id, status="running", started_at=_now_text())

        def progress_callback(**updates):
            self._update_job(job_id, **updates)

        try:
            summary = refresh_func(
                max_concepts=max_concepts,
                progress_callback=progress_callback,
            )
            self._update_job(
                job_id,
                status="completed",
                total=summary.get("concept_count") or summary.get("completed_count") or 0,
                completed=summary.get("completed_count") or summary.get("concept_count") or 0,
                current_concept="",
                stock_count=summary.get("stock_count") or 0,
                concept_count=summary.get("concept_count") or 0,
                finished_at=_now_text(),
            )
        except Exception as exc:
            self._update_job(
                job_id,
                status="failed",
                error=str(exc),
                current_concept="",
                finished_at=_now_text(),
            )

    def _normalize_job(self, job):
        now = _now_text()
        status = job.get("status") or "failed"
        if status not in TERMINAL_STATUSES and status not in {"queued", "running"}:
            status = "failed"
        if status not in TERMINAL_STATUSES:
            status = "interrupted"
            job["error"] = job.get("error") or "服务重启，概念刷新中断"
            job["finished_at"] = job.get("finished_at") or job.get("updated_at") or now

        total = int(job.get("total") or 0)
        completed = int(job.get("completed") or 0)
        progress = int(job.get("progress") or 0)
        if total:
            progress = int((completed / total) * 100)
        if status == "completed":
            progress = 100

        return {
            "id": job.get("id") or uuid.uuid4().hex[:12],
            "status": status,
            "total": total,
            "completed": completed,
            "progress": progress,
            "current_concept": "" if status in TERMINAL_STATUSES else job.get("current_concept", ""),
            "stock_count": int(job.get("stock_count") or 0),
            "concept_count": int(job.get("concept_count") or 0),
            "max_concepts": job.get("max_concepts"),
            "error": job.get("error"),
            "created_at": job.get("created_at") or now,
            "started_at": job.get("started_at"),
            "updated_at": job.get("updated_at") or now,
            "finished_at": job.get("finished_at"),
        }

    def _load_history(self):
        if self.history_path is None or not self.history_path.exists():
            return
        changed = False
        try:
            with self.history_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return

        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_job(item)
            changed = changed or normalized.get("status") == "interrupted"
            self._jobs[normalized["id"]] = normalized
        if changed:
            self._persist_jobs_unlocked()

    def _persist_jobs_unlocked(self):
        if self.history_path is None:
            return
        jobs = sorted(
            self._jobs.values(),
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )[:self.max_history]
        self._jobs = {job["id"]: job for job in jobs}
        payload = {
            "version": 1,
            "updated_at": _now_text(),
            "jobs": [self._copy_job(job) for job in jobs],
        }
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.history_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(self.history_path)
