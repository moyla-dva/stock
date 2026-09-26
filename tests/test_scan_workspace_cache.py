import unittest
import threading
import time
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from stock_analyzer.scan_workspace_cache import clear_scan_workspace_cache, get_cached_scan_workspace
from stock_analyzer.scan_workspace_persistent_cache import (
    _prune_response_cache,
    get_cached_compact_workspace_response,
    scan_workspace_dependency_fingerprint,
)


class ScanWorkspaceCacheTest(unittest.TestCase):
    def tearDown(self):
        clear_scan_workspace_cache()

    def test_cache_returns_deepcopy_and_honors_force_refresh(self):
        calls = []

        def factory():
            calls.append(1)
            return {"items": [{"count": len(calls)}]}

        first = get_cached_scan_workspace(("demo",), factory, ttl_seconds=60)
        first["items"][0]["count"] = 99
        second = get_cached_scan_workspace(("demo",), factory, ttl_seconds=60)
        refreshed = get_cached_scan_workspace(("demo",), factory, ttl_seconds=60, force_refresh=True)

        self.assertEqual(len(calls), 2)
        self.assertEqual(second["items"][0]["count"], 1)
        self.assertEqual(refreshed["items"][0]["count"], 2)

    def test_cache_single_flights_concurrent_cold_builds(self):
        calls = []
        calls_lock = threading.Lock()
        start = threading.Barrier(4)
        results = []

        def factory():
            with calls_lock:
                calls.append(1)
            time.sleep(0.05)
            return {"items": [{"count": len(calls)}]}

        def worker():
            start.wait()
            results.append(get_cached_scan_workspace(("demo",), factory, ttl_seconds=60))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(calls), 1)
        self.assertEqual([item["items"][0]["count"] for item in results], [1, 1, 1, 1])

    def test_read_only_consumer_can_reuse_cached_payload_without_deepcopy(self):
        payload = {"items": [{"code": "600001"}]}
        first = get_cached_scan_workspace(
            ("read-only",),
            lambda: payload,
            ttl_seconds=60,
            copy_payload=False,
        )
        second = get_cached_scan_workspace(
            ("read-only",),
            lambda: self.fail("cache should be reused"),
            ttl_seconds=60,
            copy_payload=False,
        )

        self.assertIs(first, payload)
        self.assertIs(second, payload)

    def test_persistent_compact_cache_uses_fingerprint_and_honors_force_refresh(self):
        calls = []

        def factory():
            calls.append(1)
            return {"items": [{"count": len(calls)}]}

        with TemporaryDirectory() as tmp_dir:
            with patch(
                "stock_analyzer.scan_workspace_persistent_cache.SCAN_WORKSPACE_RESPONSE_CACHE_DIR",
                Path(tmp_dir),
            ):
                key = ("workspace", "opportunity", 120)
                fingerprint = {"snapshots": {"file_count": 1, "latest_mtime_ns": 100}}
                first = get_cached_compact_workspace_response(key, fingerprint, factory)
                first["items"][0]["count"] = 99
                second = get_cached_compact_workspace_response(key, fingerprint, factory)
                refreshed = get_cached_compact_workspace_response(
                    key,
                    fingerprint,
                    factory,
                    force_refresh=True,
                )

        self.assertEqual(len(calls), 2)
        self.assertFalse(first["workspace_cache_meta"]["hit"])
        self.assertTrue(second["workspace_cache_meta"]["hit"])
        self.assertEqual(second["items"][0]["count"], 1)
        self.assertEqual(refreshed["items"][0]["count"], 2)

    def test_complete_scan_index_avoids_snapshot_directory_walk_for_fingerprint(self):
        class CompleteIndex:
            def cache_fingerprint(self, source_directory):
                return {
                    "available": True,
                    "revision": "snapshot-rev-1",
                    "snapshot_count": 100000,
                    "latest_snapshot_day": "20260923",
                    "build_scope": "full",
                }

        with patch(
            "stock_analyzer.scan_workspace_persistent_cache.scan_snapshot.scan_snapshot_files",
            side_effect=AssertionError("complete index should replace filesystem scan"),
        ):
            fingerprint = scan_workspace_dependency_fingerprint(index_store=CompleteIndex())

        self.assertEqual(fingerprint["snapshots"]["index_revision"], "snapshot-rev-1")
        self.assertEqual(fingerprint["snapshots"]["file_count"], 100000)

    def test_persistent_lite_workspace_cache_rejects_incomplete_payload(self):
        calls = []

        def incomplete_factory():
            calls.append("incomplete")
            return {
                "compact": True,
                "scanned_count": 1,
                "latest_snapshot_day": "2026-05-11",
                "latest_data_date": "2026-05-11",
                "pools": {"opportunity": {"results": [{"code": "600001", "name": "样本A"}]}},
            }

        def complete_factory():
            calls.append("complete")
            return {
                "compact": True,
                "snapshot_meta": {"health": "healthy"},
                "strategy_meta": {"strategy_version": "test"},
                "pools": {"opportunity": {"results": []}},
            }

        with TemporaryDirectory() as tmp_dir:
            with patch(
                "stock_analyzer.scan_workspace_persistent_cache.SCAN_WORKSPACE_RESPONSE_CACHE_DIR",
                Path(tmp_dir),
            ):
                key = ("scan_workspace_lite", "2025-04-29", "", 1, "opportunity")
                fingerprint = {"snapshots": {"file_count": 1, "latest_mtime_ns": 100}}
                incomplete = get_cached_compact_workspace_response(key, fingerprint, incomplete_factory)
                cache_files_after_incomplete = list(Path(tmp_dir).glob("*.json"))
                complete = get_cached_compact_workspace_response(key, fingerprint, complete_factory)
                cached = get_cached_compact_workspace_response(key, fingerprint, complete_factory)

        self.assertEqual(calls, ["incomplete", "complete"])
        self.assertNotIn("workspace_cache_meta", incomplete)
        self.assertEqual(cache_files_after_incomplete, [])
        self.assertFalse(complete["workspace_cache_meta"]["hit"])
        self.assertTrue(cached["workspace_cache_meta"]["hit"])
        self.assertEqual(cached["snapshot_meta"]["health"], "healthy")

    def test_persistent_compact_cache_concurrent_writes_use_unique_temps(self):
        start = threading.Barrier(4)
        results = []

        def factory():
            start.wait()
            return {"items": [{"count": 1}]}

        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            with patch(
                "stock_analyzer.scan_workspace_persistent_cache.SCAN_WORKSPACE_RESPONSE_CACHE_DIR",
                cache_dir,
            ):
                key = ("workspace", "opportunity", 120)
                fingerprint = {"snapshots": {"file_count": 1, "latest_mtime_ns": 100}}

                def worker():
                    results.append(
                        get_cached_compact_workspace_response(
                            key,
                            fingerprint,
                            factory,
                            force_refresh=True,
                        )
                    )

                threads = [threading.Thread(target=worker) for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

                leftovers = list(cache_dir.glob("*.tmp"))

        self.assertEqual(len(results), 4)
        self.assertTrue(all("workspace_cache_meta" in item for item in results))
        self.assertFalse(leftovers)

    def test_persistent_response_cache_prunes_expired_then_oldest_over_limit(self):
        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            expired = cache_dir / "expired.json"
            oldest = cache_dir / "oldest.json"
            newest = cache_dir / "newest.json"
            expired.write_text("expired", encoding="utf-8")
            oldest.write_text("1234", encoding="utf-8")
            newest.write_text("5678", encoding="utf-8")
            os.utime(expired, (0, 0))
            os.utime(oldest, (100, 100))
            os.utime(newest, (200, 200))

            with patch(
                "stock_analyzer.scan_workspace_persistent_cache.SCAN_WORKSPACE_RESPONSE_CACHE_MAX_AGE_SECONDS",
                950,
            ), patch(
                "stock_analyzer.scan_workspace_persistent_cache.SCAN_WORKSPACE_RESPONSE_CACHE_MAX_BYTES",
                5,
            ):
                removed = _prune_response_cache(cache_dir, now=1000)
                self.assertEqual(removed, 2)
                self.assertFalse(expired.exists())
                self.assertFalse(oldest.exists())
                self.assertTrue(newest.exists())

if __name__ == "__main__":
    unittest.main()
