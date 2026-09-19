import json
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import app
from stock_analyzer.scan_jobs import ScanJobManager
from stock_analyzer.scan_snapshot import build_scan_snapshot, write_scan_snapshot
from stock_analyzer.versioning import SCAN_STRATEGY_VERSION


class ScanJobsTest(unittest.TestCase):
    def _minimal_signal_frame(self, rows=10):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=rows, freq="D"),
            "open": [10.0] * rows,
            "high": [10.5] * rows,
            "low": [9.8] * rows,
            "close": [10.0 + i * 0.1 for i in range(rows)],
            "custom": [0.0] * rows,
            "dif": [0.0] * rows,
            "dea": [0.0] * rows,
            "macd_hist": [0.0] * rows,
            "ma20": [10.0] * rows,
            "vwap": [10.0] * rows,
        })
        for column in [
            "is_b_point",
            "is_pullback_b",
            "is_s_point",
            "touch_upper",
            "break_ma5",
            "is_bottom_divergence",
            "is_top_divergence",
            "new_is_b_point",
            "new_is_pullback_b",
            "new_is_s_point",
            "opt_is_b_point",
            "opt_is_pullback_b",
            "opt_is_s_warn",
            "opt_is_s_confirm",
            "opt_is_s_point",
            "composite_entry",
            "composite_risk_warn",
            "composite_exit",
            "composite_risk",
        ]:
            frame[column] = False
        frame["composite_entry_type"] = ""
        frame["composite_risk_type"] = ""
        frame["composite_exit_type"] = ""
        frame["composite_entry_reason"] = ""
        frame["composite_risk_reason"] = ""
        return frame

    def test_scan_batch_api_is_retired(self):
        client = app.app.test_client()
        response = client.post("/api/scan_batch", json={"codes": ["600063"], "scan_type": "opportunity"})
        payload = response.get_json()

        self.assertEqual(response.status_code, 410)
        self.assertEqual(payload["status"], "retired")
        self.assertEqual(payload["replacement"], "/api/scan_jobs")

    def test_scan_job_manager_tracks_background_progress(self):
        def scan_one(code, scan_type, force_refresh=False, refresh_policy="auto"):
            if code == "000002":
                return {
                    "code": code,
                    "scan_type": scan_type,
                    "signal_key": "demo",
                    "refresh_policy": refresh_policy,
                }
            return None

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=2,
                batch_size=2,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                started = manager.start_job(["000001", "000002", "000003"], "opportunity", scan_one)
                finished = manager.wait_job(started["id"], timeout=2)
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["completed"], 3)
        self.assertEqual(finished["matched"], 1)
        self.assertEqual(finished["progress"], 100)
        self.assertEqual(finished["remaining_count"], 0)
        self.assertEqual(finished["eta_seconds"], 0)
        self.assertEqual(finished["requested_count"], 3)
        self.assertEqual(finished["queued_count"], 3)
        self.assertEqual(finished["results"][0]["code"], "000002")
        self.assertEqual(finished["results"][0]["refresh_policy"], "auto")
        self.assertGreaterEqual(finished["duration_seconds"], 0)

    def test_scan_job_manager_reuses_duplicate_active_job(self):
        entered = threading.Event()
        release = threading.Event()

        def scan_one(code, scan_type, force_refresh=False, refresh_policy="auto"):
            entered.set()
            release.wait(timeout=2)
            return None

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                started = manager.start_job(
                    ["600063"],
                    "opportunity",
                    scan_one,
                    plan_summary={"scope": "market"},
                )
                self.assertTrue(entered.wait(timeout=1))
                reused = manager.start_job(
                    ["000001"],
                    "opportunity",
                    scan_one,
                    plan_summary={"scope": "market"},
                )
                release.set()
                finished = manager.wait_job(started["id"], timeout=2)
            finally:
                release.set()
                manager.shutdown(wait=True)

        self.assertEqual(reused["id"], started["id"])
        self.assertTrue(reused["duplicate_reused"])
        self.assertEqual(reused["queued_count"], 1)
        self.assertEqual(finished["status"], "completed")

    def test_scan_job_manager_reuses_concurrent_duplicate_start_requests(self):
        entered = threading.Event()
        release = threading.Event()
        start = threading.Barrier(4)
        uuid_lock = threading.Lock()
        uuid_counter = [0]
        results = []
        errors = []

        class FakeUuid:
            def __init__(self, value):
                self.hex = value

        def fake_uuid4():
            start.wait(timeout=2)
            with uuid_lock:
                uuid_counter[0] += 1
                return FakeUuid(f"{uuid_counter[0]:032x}")

        def scan_one(code, scan_type, force_refresh=False, refresh_policy="auto"):
            entered.set()
            release.wait(timeout=2)
            return None

        manager = ScanJobManager(
            max_jobs=1,
            max_workers=1,
            batch_size=1,
            batch_delay=0,
            request_delay=0,
            history_path=None,
        )
        try:
            def worker():
                try:
                    results.append(
                        manager.start_job(
                            ["600063"],
                            "opportunity",
                            scan_one,
                            plan_summary={"scope": "market"},
                        )
                    )
                except Exception as exc:
                    errors.append(exc)

            with patch("stock_analyzer.scan_jobs.uuid.uuid4", side_effect=fake_uuid4):
                threads = [threading.Thread(target=worker) for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertTrue(entered.wait(timeout=1))
            release.set()
            finished = manager.wait_job(results[0]["id"], timeout=3)
        finally:
            release.set()
            manager.shutdown(wait=True)

        self.assertFalse(errors)
        self.assertEqual(len(results), 4)
        self.assertEqual(len({item["id"] for item in results}), 1)
        self.assertEqual(sum(1 for item in results if item.get("duplicate_reused")), 3)
        self.assertEqual(finished["status"], "completed")

    def test_scan_job_manager_keeps_partial_failures_out_of_job_error(self):
        def scan_one(code, scan_type, force_refresh=False, refresh_policy="auto"):
            if code == "000001":
                raise RuntimeError("provider timeout")
            return {"code": code, "scan_type": scan_type, "signal_key": "demo"}

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=2,
                batch_size=2,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                started = manager.start_job(["000001", "600063"], "opportunity", scan_one)
                finished = manager.wait_job(started["id"], timeout=3)
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["completed"], 2)
        self.assertEqual(finished["failed"], 1)
        self.assertEqual(finished["matched"], 1)
        self.assertIsNone(finished["error"])

    def test_scan_job_manager_reports_running_eta_metrics(self):
        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                started = (datetime.now() - timedelta(seconds=60)).isoformat(timespec="seconds")
                job = manager._copy_job({
                    "id": "job_eta",
                    "status": "running",
                    "scan_type": "opportunity",
                    "refresh_policy": "auto",
                    "total": 100,
                    "completed": 25,
                    "matched": 5,
                    "failed": 0,
                    "results": [],
                    "created_at": started,
                    "started_at": started,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                })
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(job["remaining_count"], 75)
        self.assertGreater(job["eta_seconds"], 0)
        self.assertGreater(job["rate_per_minute"], 0)
        self.assertEqual(job["match_rate"], 20.0)

    def test_scan_job_manager_persists_history_for_restart(self):
        def scan_one(code, scan_type, force_refresh=False, refresh_policy="auto"):
            return {"code": code, "scan_type": scan_type, "signal_key": "demo"}

        with TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "jobs.json"
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=history_path,
            )
            try:
                started = manager.start_job(["600063"], "risk", scan_one, refresh_policy="force")
                manager.wait_job(started["id"], timeout=2)
            finally:
                manager.shutdown(wait=True)

            reloaded = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=history_path,
            )
            try:
                restored = reloaded.get_job(started["id"])
                history = reloaded.list_jobs(limit=3)
            finally:
                reloaded.shutdown(wait=True)

        self.assertEqual(restored["status"], "completed")
        self.assertEqual(restored["scan_type"], "risk")
        self.assertEqual(restored["refresh_policy"], "force")
        self.assertEqual(history[0]["id"], started["id"])
        self.assertEqual(history[0]["results"], [])

    def test_scan_job_manager_persists_history_without_results(self):
        def scan_one(code, scan_type, force_refresh=False, refresh_policy="auto"):
            return {"code": code, "scan_type": scan_type, "signal_key": "demo"}

        with TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "jobs.json"
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=history_path,
            )
            try:
                started = manager.start_job(["600063", "000001", "000002"], "opportunity", scan_one)
                manager.wait_job(started["id"], timeout=3)
            finally:
                manager.shutdown(wait=True)

            persisted = json.loads(history_path.read_text(encoding="utf-8"))

        job = persisted["jobs"][0]
        self.assertEqual(job["id"], started["id"])
        self.assertEqual(job["matched"], 3)
        self.assertEqual(job["results"], [])

    def test_scan_job_manager_can_copy_job_without_results(self):
        def scan_one(code, scan_type, force_refresh=False, refresh_policy="auto"):
            return {"code": code, "scan_type": scan_type, "signal_key": "demo"}

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                started = manager.start_job(["600063"], "opportunity", scan_one)
                manager.wait_job(started["id"], timeout=3)
                compact = manager.get_job(started["id"], include_results=False)
                full = manager.get_job(started["id"], include_results=True)
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(compact["matched"], 1)
        self.assertEqual(compact["results"], [])
        self.assertEqual(full["results"][0]["code"], "600063")

    def test_scan_job_manager_throttles_result_persistence(self):
        def scan_one(code, scan_type, force_refresh=False, refresh_policy="auto"):
            return {"code": code, "scan_type": scan_type, "signal_key": "demo"}

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                persist_every=25,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                with patch.object(manager, "_persist_jobs_unlocked", wraps=manager._persist_jobs_unlocked) as spy:
                    started = manager.start_job(["600063", "000001", "000002"], "opportunity", scan_one)
                    manager.wait_job(started["id"], timeout=3)
            finally:
                manager.shutdown(wait=True)

        # queued + started + completed；命中结果不再逐条触发持久化
        self.assertEqual(spy.call_count, 3)

    @patch("app.check_stock_signal")
    def test_scan_jobs_api_detail_omits_results_unless_requested(self, mock_check):
        mock_check.return_value = {
            "code": "600063",
            "scan_type": "opportunity",
            "signal_key": "demo",
        }

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                with patch("app.scan_job_manager", manager):
                    client = app.app.test_client()
                    response = client.post("/api/scan_jobs", json={
                        "codes": ["600063"],
                        "scan_type": "opportunity",
                        "refresh_policy": "force",
                    })
                    payload = response.get_json()
                    manager.wait_job(payload["id"], timeout=3)
                    default_detail = client.get(f"/api/scan_jobs/{payload['id']}").get_json()
                    full_detail = client.get(f"/api/scan_jobs/{payload['id']}?include_results=1").get_json()
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(default_detail["matched"], 1)
        self.assertEqual(default_detail["results"], [])
        self.assertTrue(default_detail["results_omitted"])
        self.assertEqual(full_detail["results"][0]["code"], "600063")
        self.assertNotIn("results_omitted", full_detail)

    def test_scan_job_manager_marks_running_history_interrupted(self):
        with TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "jobs.json"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(json.dumps({
                "version": 1,
                "jobs": [{
                    "id": "job123",
                    "status": "running",
                    "scan_type": "opportunity",
                    "refresh_policy": "cache",
                    "total": 10,
                    "completed": 4,
                    "matched": 1,
                    "failed": 0,
                    "progress": 40,
                    "results": [{"code": "600063"}],
                    "created_at": "2026-05-11T09:30:00",
                    "started_at": "2026-05-11T09:30:01",
                    "updated_at": "2026-05-11T09:31:00",
                }],
            }), encoding="utf-8")

            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=history_path,
            )
            try:
                restored = manager.get_job("job123")
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["refresh_policy"], "cache")
        self.assertEqual(restored["error"], "服务重启，任务中断")
        self.assertTrue(restored["restart_interrupted"])
        self.assertIn("重新启动", restored["recovery_hint"])

    def test_scan_job_manager_does_not_rewrite_already_interrupted_history(self):
        with TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "jobs.json"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            original = json.dumps({
                "version": 1,
                "updated_at": "2026-09-15T10:00:00",
                "jobs": [{
                    "id": "job123",
                    "status": "interrupted",
                    "scan_type": "opportunity",
                    "refresh_policy": "cache",
                    "total": 10,
                    "completed": 4,
                    "matched": 1,
                    "failed": 0,
                    "progress": 40,
                    "results": [{"code": "600063"}],
                    "error": "服务重启，任务中断",
                    "restart_interrupted": True,
                    "created_at": "2026-05-11T09:30:00",
                    "started_at": "2026-05-11T09:30:01",
                    "updated_at": "2026-05-11T09:31:00",
                    "finished_at": "2026-05-11T09:31:00",
                }],
            }, ensure_ascii=False)
            history_path.write_text(original, encoding="utf-8")

            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=history_path,
            )
            try:
                restored = manager.get_job("job123")
            finally:
                manager.shutdown(wait=True)

            self.assertEqual(restored["status"], "interrupted")
            self.assertEqual(history_path.read_text(encoding="utf-8"), original)

    @patch("app.check_stock_signal")
    def test_scan_jobs_api_runs_background_scan(self, mock_check):
        mock_check.return_value = {
            "code": "600063",
            "scan_type": "opportunity",
            "signal_key": "demo",
        }

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                with patch("app.scan_job_manager", manager):
                    client = app.app.test_client()
                    response = client.post("/api/scan_jobs", json={
                        "codes": ["600063"],
                        "scan_type": "opportunity",
                        "refresh_policy": "force",
                    })
                    payload = response.get_json()
                    finished = manager.wait_job(payload["id"], timeout=3)
                    status = client.get(f"/api/scan_jobs/{payload['id']}").get_json()
                    history = client.get("/api/scan_jobs?limit=3").get_json()
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(status["matched"], 1)
        self.assertEqual(status["refresh_policy"], "force")
        self.assertEqual(status["requested_count"], 1)
        self.assertEqual(status["queued_count"], 1)
        self.assertEqual(history["jobs"][0]["id"], payload["id"])
        mock_check.assert_called_once_with("600063", "opportunity", False, "force")

    @patch("app.check_stock_signal")
    def test_scan_jobs_api_auto_skips_cached_codes(self, mock_check):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                        write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        with patch("app.scan_job_manager", manager):
                            client = app.app.test_client()
                            response = client.post("/api/scan_jobs", json={
                                "codes": ["600063"],
                                "scan_type": "opportunity",
                                "refresh_policy": "auto",
                            })
                            payload = response.get_json()
                            finished = manager.wait_job(payload["id"], timeout=3)
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["total"], 0)
        self.assertEqual(finished["skipped_count"], 1)
        self.assertEqual(finished["cache_hit_count"], 1)
        self.assertEqual(finished["queued_count"], 0)
        mock_check.assert_not_called()

    def test_scan_plan_api_estimates_legacy_strategy_migration(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    snapshot.pop("strategy_version", None)
                    snapshot.pop("strategy_meta", None)
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    with patch("app.get_stock_codes") as mock_stock_codes:
                        response = app.app.test_client().post("/api/scan_plan", json={
                            "scan_type": "opportunity",
                            "refresh_policy": "auto",
                            "scope": "legacy_strategy",
                        })

        payload = response.get_json()
        mock_stock_codes.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["scan_type"], "opportunity")
        self.assertEqual(payload["refresh_policy"], "auto")
        self.assertEqual(payload["scope"], "legacy_strategy")
        self.assertEqual(payload["code_source"], "legacy_strategy")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["queued_count"], 1)
        self.assertEqual(payload["legacy_strategy_count"], 1)
        self.assertEqual(payload["cache_hit_count"], 0)
        self.assertEqual(payload["strategy_meta"]["strategy_version"], SCAN_STRATEGY_VERSION)
        self.assertGreaterEqual(payload["batch_size"], 1)
        self.assertEqual(payload["batch_count"], 1)
        self.assertTrue(payload["resume_supported"])
        self.assertIn("继续", payload["resume_note"])

    @patch("app.check_stock_signal")
    def test_scan_jobs_api_auto_queues_legacy_strategy_snapshots(self, mock_check):
        mock_check.return_value = {
            "code": "600063",
            "scan_type": "opportunity",
            "signal_key": "demo",
        }
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        with TemporaryDirectory() as tmp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=Path(tmp_dir) / "jobs.json",
            )
            try:
                with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                        snapshot.pop("strategy_version", None)
                        snapshot.pop("strategy_meta", None)
                        write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        with patch("app.scan_job_manager", manager):
                            with patch("app.get_stock_codes") as mock_stock_codes:
                                client = app.app.test_client()
                                response = client.post("/api/scan_jobs", json={
                                    "scan_type": "opportunity",
                                    "refresh_policy": "auto",
                                    "scope": "legacy_strategy",
                                })
                                payload = response.get_json()
                                finished = manager.wait_job(payload["id"], timeout=3)
            finally:
                manager.shutdown(wait=True)

        mock_stock_codes.assert_not_called()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload["legacy_strategy_count"], 1)
        self.assertEqual(payload["queued_count"], 1)
        self.assertEqual(payload["scope"], "legacy_strategy")
        self.assertEqual(payload["code_source"], "legacy_strategy")
        self.assertEqual(payload["batch_size"], 1)
        self.assertEqual(payload["batch_count"], 1)
        self.assertTrue(payload["resume_supported"])
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["legacy_strategy_count"], 1)
        self.assertEqual(finished["scope"], "legacy_strategy")
        self.assertEqual(finished["code_source"], "legacy_strategy")
        self.assertEqual(finished["batch_count"], 1)
        self.assertTrue(finished["resume_supported"])
        self.assertEqual(finished["cache_hit_count"], 0)
        mock_check.assert_called_once_with("600063", "opportunity", False, "auto")
