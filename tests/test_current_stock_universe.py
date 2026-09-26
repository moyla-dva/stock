import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock, patch

import app
from stock_analyzer.catalog import StockUniverseUnavailable, get_stock_codes
from stock_analyzer.catalog_stock_list import FALLBACK_STOCK_CODES
from stock_analyzer.current_universe import CurrentStockUniverse
from stock_analyzer.scan_jobs import ScanJobManager
from stock_analyzer.scan_service import ScanCheckOutcome, check_stock_signal


class CurrentStockUniverseTest(unittest.TestCase):
    def test_scan_universe_comes_from_revisioned_metadata_service(self):
        expected = CurrentStockUniverse(
            as_of="2026-09-23",
            revision="sha256:test",
            source="test-provider",
            coverage_status="current-provider-snapshot",
            calendar_revision="sha256:calendar",
            codes=("000001", "600001"),
        )
        with patch.object(app, "get_current_stock_universe", return_value=expected) as get_universe:
            result = app.get_scan_universe_codes()

        self.assertIs(result, expected)
        get_universe.assert_called_once_with()

    def test_market_scan_plan_exposes_the_exact_universe_revision(self):
        universe = CurrentStockUniverse(
            as_of="2026-09-23",
            revision="sha256:universe",
            source="fixture-provider",
            coverage_status="current-provider-snapshot",
            calendar_revision="sha256:calendar",
            codes=("000001",),
        )
        manager = Mock(batch_size=10, batch_delay=0, request_delay=0)
        with patch.object(app, "get_scan_universe_codes", return_value=universe), patch(
            "stock_analyzer.scan_service.plan_scan_codes",
            return_value={"codes": ["000001"], "summary": {"requested_count": 1}},
        ):
            _, summary, _ = app.build_scan_request_plan(
                {"scan_type": "opportunity"},
            )

        self.assertEqual(summary["universe_as_of"], "2026-09-23")
        self.assertEqual(summary["universe_revision"], "sha256:universe")
        self.assertEqual(summary["universe_source"], "fixture-provider")
        self.assertEqual(summary["universe_calendar_revision"], "sha256:calendar")
        self.assertEqual(summary["universe_member_count"], 1)

    def test_scan_job_retains_universe_revision(self):
        with TemporaryDirectory() as temp_dir:
            manager = ScanJobManager(
                max_jobs=1,
                max_workers=1,
                batch_size=1,
                batch_delay=0,
                request_delay=0,
                history_path=Path(temp_dir) / "jobs.json",
            )
            try:
                job = manager.start_job(
                    ["000001", "600001", "000002"],
                    "opportunity",
                    lambda code, *args: ScanCheckOutcome(None, {
                        "status": "no_data" if code == "000002" else "available",
                        "data_date": "2026-09-22" if code == "600001" else "2026-09-23",
                        "bar_state": "closed",
                        "data_source": "fixture-source",
                    }),
                    plan_summary={
                        "universe_as_of": "2026-09-23",
                        "universe_revision": "sha256:universe",
                        "universe_member_count": 3,
                    },
                )
                finished = manager.wait_job(job["id"], timeout=3)
            finally:
                manager.shutdown(wait=True)

        self.assertEqual(finished["universe_as_of"], "2026-09-23")
        self.assertEqual(finished["universe_revision"], "sha256:universe")
        self.assertEqual(finished["universe_member_count"], 3)
        self.assertEqual(finished["data_coverage"]["checked_count"], 3)
        self.assertEqual(finished["data_coverage"]["current_session_closed_count"], 1)
        self.assertEqual(finished["data_coverage"]["stale_or_no_new_bar_count"], 1)
        self.assertEqual(finished["data_coverage"]["no_data_count"], 1)

    def test_scan_job_aggregates_provider_diagnostics_and_migrates_old_coverage(self):
        job = {
            "universe_as_of": "2026-09-23",
            "data_coverage": {
                "checked_count": 0,
                "current_session_closed_count": 0,
                "intraday_preview_count": 0,
                "stale_or_no_new_bar_count": 0,
                "no_data_count": 0,
                "analysis_error_count": 0,
                "unknown_count": 0,
                "source_counts": {},
                "latest_data_date": "",
            },
        }

        ScanJobManager._accumulate_data_coverage_unlocked(
            job,
            {
                "status": "provider_error",
                "fetch_status": "provider_error",
                "cache_status": "stale",
                "fetch_attempts": [
                    {"provider": "tencent_direct", "status": "error", "error_type": "Timeout"},
                ],
            },
            "600001",
        )

        coverage = job["data_coverage"]
        self.assertEqual(coverage["no_data_count"], 1)
        self.assertEqual(coverage["provider_error_count"], 1)
        self.assertEqual(coverage["stale_cache_count"], 1)
        self.assertEqual(coverage["provider_attempt_counts"]["tencent_direct:error"], 1)
        self.assertEqual(coverage["issue_samples"][0]["code"], "600001")
        self.assertEqual(coverage["issue_samples"][0]["fetch_attempts"][0]["error_type"], "Timeout")

    def test_scan_job_samples_available_but_stale_bars_and_unknown_sources(self):
        job = {"universe_as_of": "2026-09-23"}

        ScanJobManager._accumulate_data_coverage_unlocked(
            job,
            {
                "status": "available",
                "fetch_status": "available",
                "cache_status": "miss",
                "data_date": "2026-09-22",
                "bar_state": "closed",
                "data_source": "tencent_direct",
            },
            "600001",
        )
        ScanJobManager._accumulate_data_coverage_unlocked(
            job,
            {
                "status": "available",
                "fetch_status": "available",
                "cache_status": "miss",
                "data_date": "2026-09-23",
                "bar_state": "closed",
                "data_source": "unknown",
            },
            "000001",
        )

        coverage = job["data_coverage"]
        self.assertEqual(coverage["stale_or_no_new_bar_count"], 1)
        self.assertEqual([item["code"] for item in coverage["issue_samples"]], ["600001", "000001"])
        self.assertEqual(
            coverage["issue_samples"][0]["category"],
            "stale_or_no_new_bar",
        )
        self.assertEqual(coverage["issue_samples"][1]["data_source"], "unknown")

    def test_check_outcome_preserves_provider_failure_diagnostics(self):
        outcome = check_stock_signal(
            "600001",
            refresh_policy="force",
            return_outcome=True,
            get_stock_dataframe_outcome_func=lambda code: (
                None,
                {
                    "fetch_status": "provider_error",
                    "cache_status": "stale",
                    "attempts": [{
                        "provider": "tencent_direct",
                        "status": "error",
                        "error_type": "Timeout",
                    }],
                },
            ),
        )

        self.assertIsNone(outcome.result)
        self.assertEqual(outcome.data_quality["status"], "provider_error")
        self.assertEqual(outcome.data_quality["cache_status"], "stale")
        self.assertEqual(outcome.data_quality["fetch_attempts"][0]["error_type"], "Timeout")

    def test_strict_catalog_mode_rejects_partial_fallbacks(self):
        provider = Mock()
        provider.fetch_primary_stock_codes.side_effect = OSError("offline")

        with self.assertRaises(StockUniverseUnavailable):
            get_stock_codes(
                use_disable_proxies=False,
                provider=provider,
                allow_secondary=False,
                allow_static_fallback=False,
            )

        provider.fetch_secondary_stock_codes.assert_not_called()

    def test_legacy_catalog_mode_still_returns_static_fallback(self):
        provider = Mock()
        provider.fetch_primary_stock_codes.side_effect = OSError("offline")
        provider.fetch_secondary_stock_codes.side_effect = OSError("offline")

        result = get_stock_codes(use_disable_proxies=False, provider=provider)

        self.assertEqual(result, FALLBACK_STOCK_CODES)

    def test_scan_plan_reports_retryable_universe_failure(self):
        with patch.object(app, "get_current_stock_universe", side_effect=StockUniverseUnavailable("名单源不可用")):
            response = app.app.test_client().post(
                "/api/scan_plan",
                json={"scan_type": "opportunity", "refresh_policy": "force"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "stock_universe_unavailable")
        self.assertTrue(response.get_json()["retryable"])

    def test_scan_start_does_not_create_job_without_current_universe(self):
        with patch.object(app, "get_current_stock_universe", side_effect=StockUniverseUnavailable("名单源不可用")):
            response = app.app.test_client().post(
                "/api/scan_jobs",
                json={"scan_type": "opportunity", "refresh_policy": "force"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "stock_universe_unavailable")

    def test_stock_list_reports_retryable_universe_failure(self):
        with patch.object(app, "get_current_stock_universe", side_effect=StockUniverseUnavailable("名单源不可用")):
            response = app.app.test_client().get("/api/stock_list")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "stock_universe_unavailable")
        self.assertEqual(response.get_json()["codes"], [])


if __name__ == "__main__":
    unittest.main()
