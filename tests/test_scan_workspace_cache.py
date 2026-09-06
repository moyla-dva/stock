import unittest

from stock_analyzer.scan_workspace_cache import clear_scan_workspace_cache, get_cached_scan_workspace


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


if __name__ == "__main__":
    unittest.main()
