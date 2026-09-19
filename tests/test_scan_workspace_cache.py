import unittest
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from stock_analyzer.scan_workspace_cache import clear_scan_workspace_cache, get_cached_scan_workspace
from stock_analyzer.scan_workspace_persistent_cache import get_cached_compact_workspace_response


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


if __name__ == "__main__":
    unittest.main()
