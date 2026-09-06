"""Background scan jobs with progress polling and cooperative cancellation."""

import concurrent.futures
import json
import math
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from stock_analyzer.scanner import normalize_scan_type


TERMINAL_STATUSES = {"completed", "cancelled", "failed", "interrupted"}
DEFAULT_HISTORY_PATH = Path(os.environ.get(
    "STOCK_ANALYZER_SCAN_JOB_HISTORY_PATH",
    Path(__file__).resolve().parents[1] / ".cache" / "scan_jobs" / "jobs.json",
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


class ScanJobManager:
    def __init__(
        self,
        max_jobs=2,
        max_workers=5,
        batch_size=50,
        batch_delay=1.0,
        request_delay=0.05,
        history_path=DEFAULT_HISTORY_PATH,
        max_history=50,
        persist_every=25,
    ):
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.request_delay = request_delay
        self.history_path = Path(history_path) if history_path else None
        self.max_history = max_history
        self.persist_every = persist_every
        self._lock = threading.Lock()
        self._jobs = {}
        self._job_futures = {}
        self._load_history()
        self._job_executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_jobs)
        self._scan_executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def start_job(self, codes, scan_type, scan_one, force_refresh=False, refresh_policy="auto", plan_summary=None):
        scan_type = normalize_scan_type(scan_type)
        codes = list(codes or [])
        plan_summary = dict(plan_summary or {})
        scope = plan_summary.get("scope") or "market"
        with self._lock:
            active_job = self._active_job_for_unlocked(scan_type, scope)
            if active_job is not None:
                copy = self._copy_job(active_job)
                copy["duplicate_reused"] = True
                copy["duplicate_note"] = "已有同类扫描任务运行，已接管当前任务"
                return copy

        job_id = uuid.uuid4().hex[:12]
        now = _now_text()
        strategy_meta = plan_summary.get("strategy_meta") if isinstance(plan_summary.get("strategy_meta"), dict) else {}
        job = {
            "id": job_id,
            "status": "queued",
            "scan_type": scan_type,
            "refresh_policy": refresh_policy,
            "scope": scope,
            "code_source": plan_summary.get("code_source") or "market",
            "strategy_version": strategy_meta.get("strategy_version") or plan_summary.get("strategy_version") or "",
            "strategy_label": strategy_meta.get("strategy_label") or plan_summary.get("strategy_label") or "",
            "requested_count": int(plan_summary.get("requested_count", len(codes))),
            "eligible_count": int(plan_summary.get("eligible_count", len(codes))),
            "queued_count": len(codes),
            "skipped_count": int(plan_summary.get("skipped_count", 0)),
            "cache_hit_count": int(plan_summary.get("cache_hit_count", 0)),
            "missing_count": int(plan_summary.get("missing_count", 0)),
            "stale_count": int(plan_summary.get("stale_count", 0)),
            "legacy_strategy_count": int(plan_summary.get("legacy_strategy_count", 0)),
            "missing_type_count": int(plan_summary.get("missing_type_count", 0)),
            "invalid_count": int(plan_summary.get("invalid_count", 0)),
            "total": len(codes),
            "batch_size": int(plan_summary.get("batch_size") or self.batch_size or 1),
            "batch_count": int(plan_summary.get("batch_count") or ((len(codes) + self.batch_size - 1) // self.batch_size if codes else 0)),
            "current_batch_index": 0,
            "batch_delay_seconds": float(plan_summary.get("batch_delay_seconds", self.batch_delay) or 0),
            "request_delay_seconds": float(plan_summary.get("request_delay_seconds", self.request_delay) or 0),
            "resume_supported": bool(plan_summary.get("resume_supported")),
            "resume_note": plan_summary.get("resume_note") or "",
            "restart_interrupted": False,
            "recovery_hint": plan_summary.get("recovery_hint") or "",
            "completed": 0,
            "matched": 0,
            "failed": 0,
            "progress": 0,
            "current_code": "",
            "results": [],
            "error": None,
            "cancel_requested": False,
            "created_at": now,
            "started_at": None,
            "updated_at": now,
            "finished_at": None,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._persist_jobs_unlocked()

        future = self._job_executor.submit(self._run_job, job_id, codes, scan_one, force_refresh)
        with self._lock:
            self._job_futures[job_id] = future
        return self.get_job(job_id)

    def _active_job_for_unlocked(self, scan_type, scope):
        jobs = sorted(
            self._jobs.values(),
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )
        for job in jobs:
            if job.get("status") in TERMINAL_STATUSES:
                continue
            if normalize_scan_type(job.get("scan_type")) != scan_type:
                continue
            if (job.get("scope") or "market") != (scope or "market"):
                continue
            return job
        return None

    def get_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return self._copy_job(job)

    def cancel_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job["status"] not in TERMINAL_STATUSES:
                job["cancel_requested"] = True
                job["status"] = "cancelling"
                job["updated_at"] = _now_text()
                self._persist_jobs_unlocked()
            return self._copy_job(job)

    def list_jobs(self, limit=20):
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda item: item.get("created_at") or "",
                reverse=True,
            )
            return [self._copy_job(job, include_results=False) for job in jobs[:limit]]

    def wait_job(self, job_id, timeout=None):
        with self._lock:
            future = self._job_futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get_job(job_id)

    def shutdown(self, wait=True):
        self._job_executor.shutdown(wait=wait)
        self._scan_executor.shutdown(wait=wait)

    def _copy_job(self, job, include_results=True):
        copy = dict(job)
        if include_results:
            copy["results"] = [dict(item) for item in job.get("results", [])]
        else:
            copy["results"] = []
        duration_seconds = self._duration_seconds(job)
        copy["duration_seconds"] = duration_seconds
        copy.update(self._progress_metrics(job, duration_seconds))
        return copy

    def _progress_metrics(self, job, duration_seconds):
        total = int(job.get("total") or 0)
        completed = int(job.get("completed") or 0)
        matched = int(job.get("matched") or len(job.get("results") or []))
        failed = int(job.get("failed") or 0)
        status = job.get("status") or "queued"
        remaining = max(0, total - completed)
        if status == "completed":
            remaining = 0

        rate_per_minute = None
        eta_seconds = None
        if duration_seconds is not None and duration_seconds > 0 and completed > 0:
            rate_per_second = completed / duration_seconds
            rate_per_minute = round(rate_per_second * 60, 1)
            if status not in TERMINAL_STATUSES and remaining > 0 and rate_per_second > 0:
                eta_seconds = int(math.ceil(remaining / rate_per_second))

        if status == "completed":
            eta_seconds = 0

        match_rate = round(matched / completed * 100, 1) if completed > 0 else None
        fail_rate = round(failed / completed * 100, 1) if completed > 0 else None
        return {
            "remaining_count": remaining,
            "eta_seconds": eta_seconds,
            "rate_per_minute": rate_per_minute,
            "match_rate": match_rate,
            "fail_rate": fail_rate,
        }

    def _update_job(self, job_id, **updates):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.update(updates)
            job["updated_at"] = _now_text()
            total = job.get("total") or 0
            completed = job.get("completed") or 0
            job["progress"] = 100 if total == 0 else int((completed / total) * 100)
            if self._should_persist_update(updates):
                self._persist_jobs_unlocked()
            return self._copy_job(job)

    def _is_cancel_requested(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.get("cancel_requested"))

    def _append_result(self, job_id, result=None, failed=False, current_code=""):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job["completed"] += 1
            if failed:
                job["failed"] += 1
            if result:
                job["results"].append(dict(result))
                job["matched"] = len(job["results"])
            job["current_code"] = current_code
            job["updated_at"] = _now_text()
            total = job.get("total") or 0
            job["progress"] = 100 if total == 0 else int((job["completed"] / total) * 100)
            if job["completed"] % self.persist_every == 0 or result:
                self._persist_jobs_unlocked()
            return self._copy_job(job)

    def _should_persist_update(self, updates):
        return bool({"status", "started_at", "finished_at", "error"} & set(updates.keys()))

    def _run_job(self, job_id, codes, scan_one, force_refresh):
        self._update_job(job_id, status="running", started_at=_now_text())
        try:
            for batch_start in range(0, len(codes), self.batch_size):
                if self._is_cancel_requested(job_id):
                    self._finish_cancelled(job_id)
                    return

                batch = codes[batch_start:batch_start + self.batch_size]
                self._update_job(job_id, current_batch_index=(batch_start // self.batch_size) + 1)
                futures = {}
                for code in batch:
                    if self._is_cancel_requested(job_id):
                        break
                    self._update_job(job_id, current_code=code)
                    scan_type, refresh_policy = self._scan_job_mode(job_id)
                    future = self._scan_executor.submit(scan_one, code, scan_type, force_refresh, refresh_policy)
                    futures[future] = code
                    if self.request_delay:
                        time.sleep(self.request_delay)

                for future in concurrent.futures.as_completed(futures):
                    code = futures[future]
                    if self._is_cancel_requested(job_id):
                        for pending in futures:
                            pending.cancel()
                        self._finish_cancelled(job_id)
                        return
                    try:
                        result = future.result()
                    except Exception as exc:
                        self._update_job(job_id, error=str(exc))
                        self._append_result(job_id, failed=True, current_code=code)
                        continue
                    self._append_result(job_id, result=result, current_code=code)

                if batch_start + self.batch_size < len(codes) and self.batch_delay:
                    time.sleep(self.batch_delay)

            self._update_job(
                job_id,
                status="completed",
                progress=100,
                current_code="",
                finished_at=_now_text(),
            )
        except Exception as exc:
            self._update_job(
                job_id,
                status="failed",
                error=str(exc),
                current_code="",
                finished_at=_now_text(),
            )

    def _scan_job_mode(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return "opportunity", "auto"
            return job["scan_type"], job.get("refresh_policy", "auto")

    def _finish_cancelled(self, job_id):
        self._update_job(
            job_id,
            status="cancelled",
            current_code="",
            finished_at=_now_text(),
        )

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

    def _normalize_job(self, job):
        now = _now_text()
        status = job.get("status") or "failed"
        if status not in TERMINAL_STATUSES and status != "queued" and status != "running" and status != "cancelling":
            status = "failed"
        if status not in TERMINAL_STATUSES:
            status = "interrupted"
            job["error"] = job.get("error") or "服务重启，任务中断"
            job["finished_at"] = job.get("finished_at") or job.get("updated_at") or now
            job["restart_interrupted"] = True
            job["recovery_hint"] = job.get("recovery_hint") or (
                "重新启动同类增量任务会复用已有快照，只补未完成部分"
                if job.get("refresh_policy") == "auto"
                else "任务已中断，请按需重新启动扫描"
            )
        normalized = {
            "id": job.get("id") or uuid.uuid4().hex[:12],
            "status": status,
            "scan_type": normalize_scan_type(job.get("scan_type")),
            "refresh_policy": job.get("refresh_policy") or "auto",
            "scope": job.get("scope") or "market",
            "code_source": job.get("code_source") or "market",
            "strategy_version": job.get("strategy_version") or "",
            "strategy_label": job.get("strategy_label") or "",
            "requested_count": int(job.get("requested_count") or job.get("total") or 0),
            "eligible_count": int(job.get("eligible_count") or job.get("total") or 0),
            "queued_count": int(job.get("queued_count") or job.get("total") or 0),
            "skipped_count": int(job.get("skipped_count") or 0),
            "cache_hit_count": int(job.get("cache_hit_count") or 0),
            "missing_count": int(job.get("missing_count") or 0),
            "stale_count": int(job.get("stale_count") or 0),
            "legacy_strategy_count": int(job.get("legacy_strategy_count") or 0),
            "missing_type_count": int(job.get("missing_type_count") or 0),
            "invalid_count": int(job.get("invalid_count") or 0),
            "total": int(job.get("total") or 0),
            "batch_size": int(job.get("batch_size") or self.batch_size or 1),
            "batch_count": int(job.get("batch_count") or 0),
            "current_batch_index": int(job.get("current_batch_index") or 0),
            "batch_delay_seconds": float(job.get("batch_delay_seconds") or self.batch_delay or 0),
            "request_delay_seconds": float(job.get("request_delay_seconds") or self.request_delay or 0),
            "resume_supported": bool(job.get("resume_supported")),
            "resume_note": job.get("resume_note") or "",
            "restart_interrupted": bool(job.get("restart_interrupted")),
            "recovery_hint": job.get("recovery_hint") or "",
            "completed": int(job.get("completed") or 0),
            "matched": int(job.get("matched") or len(job.get("results") or [])),
            "failed": int(job.get("failed") or 0),
            "progress": int(job.get("progress") or 0),
            "current_code": "" if status in TERMINAL_STATUSES else job.get("current_code", ""),
            "results": [dict(item) for item in job.get("results", [])],
            "error": job.get("error"),
            "cancel_requested": False,
            "created_at": job.get("created_at") or now,
            "started_at": job.get("started_at"),
            "updated_at": job.get("updated_at") or now,
            "finished_at": job.get("finished_at"),
        }
        if normalized["total"]:
            normalized["progress"] = int((normalized["completed"] / normalized["total"]) * 100)
        if normalized["status"] in TERMINAL_STATUSES and normalized["completed"] >= normalized["total"]:
            normalized["progress"] = 100
        return normalized

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
