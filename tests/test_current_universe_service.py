import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from stock_analyzer.catalog_stock_list import StockUniverseUnavailable
from stock_analyzer.current_universe import CurrentUniverseService
from stock_analyzer.market_metadata_store import MarketMetadataStore


class CurrentUniverseServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MarketMetadataStore(Path(self.temp_dir.name) / "market.sqlite3")
        self.store.import_trading_calendar(
            ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28"],
            source="fixture-calendar",
            evidence_level="exchange-official",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _members():
        return [
            {
                "code": "600001",
                "name": "Sample SSE",
                "exchange": "SSE",
                "listing_date": "2000-01-01",
                "member_source": "sse_current_main",
            },
            {
                "code": "000001",
                "name": "Sample SZSE",
                "exchange": "SZSE",
                "listing_date": "2000-01-01",
                "member_source": "szse_current",
            },
            {
                "code": "830001",
                "name": "Sample BSE",
                "exchange": "BSE",
                "listing_date": "2021-11-15",
                "member_source": "bse_current",
            },
        ]

    @staticmethod
    def _coverage():
        return {
            "membership": {
                "SSE": {"status": "available"},
                "SZSE": {"status": "available"},
                "BSE": {"status": "available"},
            },
        }

    def _payload(self, as_of):
        return SimpleNamespace(
            as_of=as_of,
            members=self._members(),
            source="fixture-current-provider",
            evidence_level="provider-derived",
            coverage_status="current-provider-snapshot",
            coverage=self._coverage(),
            warnings=(),
        )

    def test_refreshes_missing_session_once_and_returns_written_revision(self):
        calls = []

        def load(as_of, *, observed_on):
            calls.append((as_of, observed_on))
            return self._payload(as_of)

        service = CurrentUniverseService(
            self.store,
            universe_loader=load,
            now=lambda: datetime.fromisoformat("2026-09-23T10:00:00+08:00"),
        )

        first = service.get()
        second = service.get()

        self.assertEqual(calls, [("2026-09-23", "2026-09-23")])
        self.assertEqual(first.revision, second.revision)
        self.assertEqual(first.as_of, "2026-09-23")
        self.assertEqual(first.codes, ("000001", "600001", "830001"))
        self.assertEqual(first.calendar_revision, self.store.calendar_status()["revision"])

    def test_reuses_existing_exact_snapshot_without_network_refresh(self):
        imported = self.store.import_universe_snapshot(
            "2026-09-23",
            self._members(),
            source="stored-current-provider",
            evidence_level="provider-derived",
            coverage_status="current-provider-snapshot",
            coverage=self._coverage(),
        )
        service = CurrentUniverseService(
            self.store,
            universe_loader=lambda *args, **kwargs: self.fail("should reuse snapshot"),
            now=lambda: datetime.fromisoformat("2026-09-23T10:00:00+08:00"),
        )

        result = service.get()

        self.assertEqual(result.revision, imported["revision"])
        self.assertEqual(result.source, "stored-current-provider")

    def test_non_session_reuses_last_session_snapshot_and_does_not_rebuild_history(self):
        imported = self.store.import_universe_snapshot(
            "2026-09-25",
            self._members(),
            source="stored-current-provider",
            evidence_level="provider-derived",
            coverage_status="current-provider-snapshot",
            coverage=self._coverage(),
        )
        service = CurrentUniverseService(
            self.store,
            universe_loader=lambda *args, **kwargs: self.fail("must not fetch historical membership"),
            now=lambda: datetime.fromisoformat("2026-09-26T10:00:00+08:00"),
        )

        result = service.get()

        self.assertEqual(result.as_of, "2026-09-25")
        self.assertEqual(result.revision, imported["revision"])

    def test_non_session_without_snapshot_fails_instead_of_inventing_membership(self):
        service = CurrentUniverseService(
            self.store,
            universe_loader=lambda *args, **kwargs: self.fail("must not fetch historical membership"),
            now=lambda: datetime.fromisoformat("2026-09-26T10:00:00+08:00"),
        )

        with self.assertRaisesRegex(StockUniverseUnavailable, "非交易日"):
            service.get()

    def test_failed_refresh_does_not_write_a_snapshot(self):
        service = CurrentUniverseService(
            self.store,
            universe_loader=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
            now=lambda: datetime.fromisoformat("2026-09-23T10:00:00+08:00"),
        )

        with self.assertRaisesRegex(StockUniverseUnavailable, "offline"):
            service.get()

        self.assertFalse(self.store.universe_as_of("2026-09-23")["available"])

    def test_concurrent_refreshes_share_one_upstream_request(self):
        calls = []
        entered = threading.Event()
        release = threading.Event()

        def load(as_of, *, observed_on):
            calls.append((as_of, observed_on))
            entered.set()
            release.wait(timeout=2)
            return self._payload(as_of)

        service = CurrentUniverseService(
            self.store,
            universe_loader=load,
            now=lambda: datetime.fromisoformat("2026-09-23T10:00:00+08:00"),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(service.get)
            self.assertTrue(entered.wait(timeout=1))
            second = executor.submit(service.get)
            time.sleep(0.05)
            release.set()
            first_result = first.result(timeout=2)
            second_result = second.result(timeout=2)

        self.assertEqual(calls, [("2026-09-23", "2026-09-23")])
        self.assertEqual(first_result.revision, second_result.revision)


if __name__ == "__main__":
    unittest.main()
