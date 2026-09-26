import unittest
from unittest.mock import patch

from stock_analyzer.current_universe_audit import audit_current_universe_scan


class CurrentUniverseAuditTest(unittest.TestCase):
    class Store:
        def __init__(self, *, available=True, eligible=True):
            self.available = available
            self.eligible = eligible

        def universe_as_of(self, as_of):
            if not self.available:
                return {"available": False, "exact_match": False, "member_count": 0}
            return {
                "available": True,
                "exact_match": True,
                "revision": "universe-rev-1",
                "source": "test-provider",
                "coverage_status": "current-provider-snapshot",
                "member_count": 2,
                "warnings": [],
            }

        def universe_coverage_report(self, as_of):
            return {"current_scan_eligible": self.eligible}

        def session_context(self, as_of):
            return {
                "is_session": True,
                "calendar_revision": "calendar-rev-1",
                "calendar_evidence_level": "exchange-official",
            }

    def _job(self, **overrides):
        job = {
            "id": "job-1",
            "status": "completed",
            "scope": "market",
            "code_source": "market",
            "universe_as_of": "2026-09-23",
            "universe_revision": "universe-rev-1",
            "universe_source": "test-provider",
            "universe_coverage_status": "current-provider-snapshot",
            "universe_member_count": 2,
            "universe_calendar_revision": "calendar-rev-1",
            "scan_type": "opportunity",
        }
        job.update(overrides)
        return job

    def test_matching_market_scan_is_consistent(self):
        report = audit_current_universe_scan(
            "2026-09-23",
            self.Store(),
            [self._job()],
        )

        self.assertEqual(report["status"], "consistent")
        self.assertEqual(report["market_scan_jobs"][0]["mismatches"], {})

    def test_revision_or_member_count_drift_is_reported(self):
        report = audit_current_universe_scan(
            "2026-09-23",
            self.Store(),
            [self._job(universe_revision="old-revision", universe_member_count="3")],
        )

        self.assertEqual(report["status"], "mismatch")
        self.assertEqual(
            set(report["market_scan_jobs"][0]["mismatches"]),
            {"universe_revision", "universe_member_count"},
        )

    def test_custom_scan_does_not_count_as_market_observation(self):
        report = audit_current_universe_scan(
            "2026-09-23",
            self.Store(),
            [self._job(code_source="custom")],
        )

        self.assertEqual(report["status"], "awaiting_market_scan")
        self.assertEqual(report["market_scan_jobs"], [])

    def test_ineligible_universe_blocks_consistency_gate(self):
        report = audit_current_universe_scan(
            "2026-09-23",
            self.Store(eligible=False),
            [self._job()],
        )

        self.assertEqual(report["status"], "universe_not_scan_eligible")

    def test_missing_exact_date_universe_does_not_fall_back(self):
        report = audit_current_universe_scan(
            "2026-09-23",
            self.Store(available=False),
            [self._job()],
        )

        self.assertEqual(report["status"], "missing_universe_snapshot")
        self.assertNotIn("expected", report)

    def test_scan_completion_records_universe_audit_in_postprocess_result(self):
        import app

        job = self._job(
            started_at="2026-09-23T10:00:00",
            universe_calendar_revision="calendar-rev-1",
        )
        with (
            patch("app.market_metadata_store", self.Store()),
            patch("app.scan_snapshot_paths_for_codes", return_value=[]),
        ):
            result = app.sync_scan_job_index(job, ["600001", "600002"])

        self.assertEqual(result["status"], "no_snapshots")
        self.assertEqual(result["universe_consistency"]["status"], "consistent")


if __name__ == "__main__":
    unittest.main()
