import sqlite3
import tempfile
import unittest
from pathlib import Path

from stock_analyzer.market_metadata_store import MarketMetadataStore


class MarketMetadataStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "market_metadata.sqlite3"
        self.store = MarketMetadataStore(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_calendar_queries_are_versioned_and_unknown_outside_coverage(self):
        imported = self.store.import_trading_calendar(
            ["2026-09-21", "20260922", "2026-09-24"],
            source="fixture-calendar",
            evidence_level="validated",
            imported_at="2026-09-23T00:00:00+00:00",
        )

        self.assertTrue(imported["available"])
        self.assertEqual(imported["coverage_start"], "2026-09-21")
        self.assertEqual(imported["coverage_end"], "2026-09-24")
        self.assertEqual(imported["session_count"], 3)
        self.assertTrue(self.store.is_trading_session("2026-09-22"))
        self.assertFalse(self.store.is_trading_session("2026-09-23"))
        self.assertIsNone(self.store.is_trading_session("2026-09-25"))
        self.assertEqual(
            self.store.adjacent_trading_session(
                "2026-09-23", direction="previous"
            ),
            "2026-09-22",
        )
        self.assertEqual(
            self.store.adjacent_trading_session("2026-09-23", direction="next"),
            "2026-09-24",
        )

    def test_new_calendar_revision_becomes_active_without_deleting_history(self):
        first = self.store.import_trading_calendar(
            ["2026-09-21", "2026-09-22"],
            source="fixture-v1",
            evidence_level="exploratory",
        )
        second = self.store.import_trading_calendar(
            ["2026-09-21", "2026-09-23"],
            source="fixture-v2",
            evidence_level="validated",
        )

        self.assertNotEqual(first["revision"], second["revision"])
        self.assertEqual(self.store.calendar_status()["revision"], second["revision"])
        self.assertFalse(self.store.is_trading_session("2026-09-22"))
        self.assertTrue(self.store.is_trading_session("2026-09-23"))

    def test_calendar_context_uses_highest_priority_date_evidence(self):
        self.store.import_trading_calendar(
            ["2025-12-31", "2026-09-21", "2026-09-22", "2026-12-31"],
            source="mixed-calendar",
            evidence_level="mixed",
            evidence_segments=[
                {
                    "coverage_start": "2025-12-31",
                    "coverage_end": "2026-12-31",
                    "source": "provider baseline",
                    "evidence_level": "provider",
                    "priority": 10,
                },
                {
                    "coverage_start": "2026-01-01",
                    "coverage_end": "2026-12-31",
                    "source": "SSE official notice",
                    "evidence_level": "exchange-official",
                    "source_url": "https://example.test/sse",
                    "priority": 100,
                },
                {
                    "coverage_start": "2026-01-01",
                    "coverage_end": "2026-12-31",
                    "source": "SZSE official notice",
                    "evidence_level": "exchange-official",
                    "source_url": "https://example.test/szse",
                    "priority": 100,
                },
            ],
        )

        historical = self.store.session_context("2025-12-31")
        official = self.store.session_context("2026-09-22")
        closure = self.store.session_context("2026-09-23")

        self.assertEqual(historical["calendar_evidence_level"], "provider")
        self.assertEqual(official["calendar_evidence_level"], "exchange-official")
        self.assertEqual(
            official["calendar_source"],
            "SSE official notice; SZSE official notice",
        )
        self.assertEqual(len(official["calendar_source_urls"]), 2)
        self.assertTrue(official["is_session"])
        self.assertFalse(closure["is_session"])

    def test_universe_defaults_to_exact_snapshot_and_fallback_is_explicit(self):
        imported = self.store.import_universe_snapshot(
            "2026-09-22",
            [
                {
                    "code": "sh600001",
                    "name": "Sample A",
                    "exchange": "SSE",
                    "listing_date": "2000-01-01",
                    "member_source": "sse_current",
                },
                {"code": "000002", "name": "Sample B", "exchange": "SZSE"},
            ],
            source="fixture-universe",
            evidence_level="validated",
            coverage_status="declared-complete",
            coverage={
                "membership": {
                    "SSE": {"status": "available"},
                    "SZSE": {"status": "available"},
                }
            },
            warnings=["fixture warning"],
            imported_at="2026-09-23T00:00:00+00:00",
        )

        self.assertTrue(imported["available"])
        self.assertTrue(imported["exact_match"])
        self.assertEqual([item["code"] for item in imported["members"]], ["000002", "600001"])
        self.assertEqual(imported["coverage_status"], "declared-complete")
        self.assertEqual(
            imported["coverage"]["membership"]["SSE"]["status"],
            "available",
        )
        self.assertEqual(imported["warnings"], ["fixture warning"])
        self.assertEqual(imported["members"][1]["listing_date"], "2000-01-01")
        self.assertEqual(imported["members"][1]["member_source"], "sse_current")

        missing = self.store.universe_as_of("2026-09-23")
        self.assertFalse(missing["available"])
        self.assertFalse(missing["fallback_used"])

        fallback = self.store.universe_as_of("2026-09-23", allow_previous=True)
        self.assertTrue(fallback["available"])
        self.assertFalse(fallback["exact_match"])
        self.assertTrue(fallback["fallback_used"])
        self.assertEqual(fallback["resolved_as_of"], "2026-09-22")
        self.assertEqual(fallback["source"], "fixture-universe")

    def test_empty_or_invalid_imports_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one session"):
            self.store.import_trading_calendar(
                [], source="fixture", evidence_level="validated"
            )
        with self.assertRaisesRegex(ValueError, "invalid A-share stock code"):
            self.store.import_universe_snapshot(
                "2026-09-22",
                [{"code": "ABC"}],
                source="fixture",
                evidence_level="validated",
            )

    def test_universe_coverage_report_separates_current_and_historical_use(self):
        self.store.import_universe_snapshot(
            "2026-09-22",
            [
                {
                    "code": "600001",
                    "name": "Sample A",
                    "exchange": "SSE",
                    "listing_date": "2000-01-01",
                    "member_source": "sse_current",
                },
                {
                    "code": "000002",
                    "name": "Sample B",
                    "exchange": "SZSE",
                    "listing_date": "2001-01-01",
                    "member_source": "szse_current",
                },
                {
                    "code": "830001",
                    "name": "Sample BSE",
                    "exchange": "BSE",
                    "listing_date": "2021-11-15",
                    "member_source": "bse_current",
                },
            ],
            source="fixture-universe",
            evidence_level="provider-derived",
            coverage_status="partial",
            coverage={
                "membership": {
                    "SSE": {"status": "available"},
                    "SZSE": {"status": "available"},
                    "BSE": {"status": "available"},
                },
                "delisting_history": {
                    "SSE": {"status": "available"},
                    "SZSE": {"status": "available"},
                    "BSE": {"status": "missing"},
                },
                "security_name_history": {
                    "ALL": {"status": "missing", "impact": "display"},
                },
                "governance": {
                    "usage_terms": {"status": "unreviewed", "impact": "governance"},
                },
            },
        )

        report = self.store.universe_coverage_report("2026-09-22")

        self.assertTrue(report["current_scan_eligible"])
        self.assertFalse(report["historical_research_eligible"])
        self.assertEqual(report["blocking_gaps"], ["delisting_history.BSE"])
        self.assertEqual(
            report["informational_gaps"],
            ["security_name_history.ALL"],
        )
        self.assertEqual(report["governance_gaps"], ["governance.usage_terms"])
        self.assertEqual(report["exchange_counts"], {"BSE": 1, "SSE": 1, "SZSE": 1})
        self.assertEqual(
            report["field_completeness"]["listing_date"]["coverage_ratio"],
            1.0,
        )
        self.assertEqual(report["temporal_errors"]["listed_after_as_of"], [])

    def test_universe_coverage_report_blocks_incomplete_current_membership(self):
        members = [
            {"code": "600001", "name": "SSE", "exchange": "SSE", "member_source": "sse"},
            {"code": "000001", "name": "SZSE", "member_source": "szse", "exchange": "SZSE"},
            {"code": "830001", "name": "BSE", "exchange": "BSE", "member_source": "bse"},
        ]

        for index, status in enumerate(("partial", "unknown", "missing", "unavailable", None)):
            with self.subTest(status=status):
                as_of = f"2026-09-{20 + index:02d}"
                membership = {
                    "SSE": {"status": "available"},
                    "SZSE": {"status": "available"},
                }
                if status is not None:
                    membership["BSE"] = {"status": status}
                self.store.import_universe_snapshot(
                    as_of,
                    members,
                    source="fixture-universe",
                    evidence_level="provider-derived",
                    coverage_status="complete",
                    coverage={
                        "membership": membership,
                    },
                )

                report = self.store.universe_coverage_report(as_of)

                self.assertFalse(report["current_scan_eligible"])
                self.assertFalse(report["historical_research_eligible"])
                self.assertIn("membership.BSE", report["blocking_gaps"])

    def test_status_does_not_claim_missing_reference_data(self):
        status = self.store.status()

        self.assertEqual(status["schema_version"], 5)
        self.assertEqual(status["calendar_count"], 0)
        self.assertEqual(status["universe_snapshot_count"], 0)
        self.assertEqual(status["latest_universe_as_of"], "")

    def test_v1_database_migrates_universe_provenance_columns(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript("""
                CREATE TABLE universe_imports (
                    revision TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    source TEXT NOT NULL,
                    evidence_level TEXT NOT NULL,
                    member_count INTEGER NOT NULL,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE universe_members (
                    as_of TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    listing_status TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    PRIMARY KEY(as_of, code, source_revision)
                );
                PRAGMA user_version = 1;
            """)

        MarketMetadataStore(legacy_path).initialize()

        with sqlite3.connect(legacy_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            import_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(universe_imports)")
            }
            member_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(universe_members)")
            }
            evidence_rows = connection.execute(
                "SELECT COUNT(*) FROM calendar_evidence_segments"
            ).fetchone()[0]
        self.assertEqual(version, 5)
        self.assertTrue(
            {"coverage_status", "warnings_json", "coverage_json"} <= import_columns
        )
        self.assertTrue(
            {"listing_date", "delisting_date", "member_source"} <= member_columns
        )
        self.assertEqual(evidence_rows, 0)


if __name__ == "__main__":
    unittest.main()
