import sqlite3
import unittest
from argparse import Namespace

from scripts.audit_candidate_ranking_v1 import (
    _calendar_index,
    _market_context_for_audit,
    _rank_context,
)
from stock_analyzer.candidate_ranking_v1 import (
    build_calendar_session_index,
    build_candidate_ranking_features_v1,
)


def _candidate(
    *,
    pool="opportunity",
    permission="pullback_allowed",
    plan_status="ready",
    environment="allowed",
    state="entry_pullback",
    role="candidate",
    data_date="2026-09-24",
    bar_state="closed",
):
    snapshot = {
        "code": "600001",
        "snapshot_day": "20260924",
        "data_date": data_date,
        "bar_state": bar_state,
        "data_source": "fixture-provider",
        "data_revision": "sha256:data",
        "calendar_id": "XSHG",
        "calendar_revision": "sha256:calendar",
        "calendar_evidence_level": "exchange-official",
    }
    result = {
        "code": "600001",
        "price": 10.5,
        "date": data_date,
        "v2_permission": permission,
        "v2_plan_status": plan_status,
        "v2_environment_permission": environment,
        "setup_score": 1,
        "confirm_score": 1,
        "risk_score": 1,
        "market_boost": None,
        "v2_state_model": {
            "state": state,
            "role": role,
            "permission": permission,
            "v2_permission_model": {"plan_status": plan_status},
            "facts": {
                "latest_date": data_date,
                "scores": {"setup": 1, "confirm": 1, "risk": 1},
                "v2_scores": {
                    "structure_score": 95,
                    "trigger_quality": 90,
                    "research_score": 80,
                    "execution_risk": 10,
                },
                "structure": {},
                "setup": {},
                "trigger": {},
                "momentum": {},
                "risk": {},
            },
        },
    }
    return snapshot, result


class CandidateRankingV1FeatureTest(unittest.TestCase):
    def test_batch_audit_normalizes_compact_snapshot_day_for_calendar_lookup(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "create table trading_sessions (calendar_id, source_revision, session_date)"
        )
        connection.executemany(
            "insert into trading_sessions values (?, ?, ?)",
            [
                ("XSHG", "sha256:calendar", "2026-09-23"),
                ("XSHG", "sha256:calendar", "2026-09-24"),
                ("XSHG", "sha256:calendar", "2026-09-25"),
            ],
        )

        index = _calendar_index(
            connection,
            {
                "calendar_id": "XSHG",
                "calendar_revision": "sha256:calendar",
                "snapshot_day": "20260924",
            },
            {},
        )

        self.assertEqual(index, {"2026-09-23": 0, "2026-09-24": 1})
        connection.close()

    def test_ready_requires_current_data_plan_and_known_allowed_environment(self):
        snapshot, result = _candidate()

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["eligibility_tier"], "ready")
        self.assertEqual(features["data_quality"]["status"], "current")

    def test_unknown_environment_prevents_ready_without_becoming_forbidden(self):
        snapshot, result = _candidate(environment="unknown")

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["eligibility_tier"], "waiting")
        self.assertIn("environment_unknown", features["eligibility_reasons"])

    def test_numeric_market_adjustment_without_provenance_is_unknown(self):
        snapshot, result = _candidate()

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
            market_context={"market_adjustment": 2.5},
        )

        self.assertEqual(features["market_context"]["adjustment"], 2.5)
        self.assertEqual(features["market_context"]["status"], "unknown")

    def test_market_adjustment_is_current_only_with_asof_and_revision(self):
        snapshot, result = _candidate()

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
            market_context={
                "market_adjustment": 2.5,
                "status": "current",
                "as_of": "2026-09-24",
                "revision": "sha256:board-market",
            },
        )

        self.assertEqual(features["market_context"]["status"], "current")
        self.assertEqual(features["market_context"]["revision"], "sha256:board-market")

    def test_contextual_environment_overrides_snapshot_local_unknown(self):
        snapshot, result = _candidate(environment="unknown")

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
            environment_permission="allowed",
        )

        self.assertEqual(features["environment_permission"], "allowed")
        self.assertEqual(features["eligibility_tier"], "ready")

    def test_audit_uses_market_component_asof_against_snapshot_session(self):
        context = {
            "market_adjustment": 2.5,
            "revision": "sha256:rank-context",
            "market_components": {
                "sector": {
                    "source": "tencent_direct",
                    "as_of": "2026-09-24",
                    "adjustment": 2.5,
                    "cache_stale": False,
                },
            },
        }

        audited = _market_context_for_audit(context, "2026-09-24")

        self.assertEqual(audited["status"], "current")
        self.assertEqual(audited["as_of"], "2026-09-24")
        self.assertEqual(audited["revision"], "sha256:rank-context")

    def test_audit_marks_future_market_input_instead_of_current(self):
        context = {
            "market_adjustment": 2.5,
            "revision": "sha256:rank-context",
            "market_components": {
                "sector": {
                    "source": "tencent_direct",
                    "as_of": "2026-09-25",
                    "adjustment": 2.5,
                    "cache_stale": False,
                },
            },
        }

        audited = _market_context_for_audit(context, "2026-09-24")

        self.assertEqual(audited["status"], "future")

    def test_audit_keeps_legacy_numeric_context_unknown_without_provenance(self):
        audited = _market_context_for_audit(
            {"market_adjustment": 2.5, "revision": "sha256:legacy"},
            "2026-09-24",
        )

        self.assertEqual(audited["status"], "unknown")

    def test_audit_reads_persisted_rank_context_environment_and_market_provenance(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE rank_context_runs (
                context_revision TEXT, status TEXT, candidate_count INTEGER,
                computed_at TEXT, source_fingerprint_json TEXT
            );
            CREATE TABLE rank_context_heads (run_key TEXT, context_revision TEXT);
            CREATE TABLE candidate_summaries (
                id INTEGER, pool TEXT, code TEXT, snapshot_day TEXT,
                strategy_version TEXT, start_key TEXT
            );
            CREATE TABLE candidate_rank_contexts (
                context_revision TEXT, candidate_id INTEGER, market_boost REAL,
                context_priority_group TEXT, environment_permission TEXT,
                market_context_json TEXT
            );
            """
        )
        run_key = "20260924:2026.09.20.1:20250429:latest_fresh"
        revision = "sha256:rank-context"
        connection.execute(
            "INSERT INTO rank_context_runs VALUES (?, 'complete', 1, ?, ?)",
            (revision, "2026-09-24T10:00:00+00:00", '{"workspace_profile":{}}'),
        )
        connection.execute(
            "INSERT INTO rank_context_heads VALUES (?, ?)", (run_key, revision)
        )
        connection.execute(
            "INSERT INTO candidate_summaries VALUES (1, 'opportunity', '600001', ?, ?, ?)",
            ("20260924", "2026.09.20.1", "20250429"),
        )
        connection.execute(
            "INSERT INTO candidate_rank_contexts VALUES (?, 1, 2.5, 'trade_ready', 'allowed', ?)",
            (
                revision,
                '{"sector":{"source":"tencent_direct","as_of":"2026-09-24","adjustment":2.5,"input_revision":"sha256:market"}}',
            ),
        )

        metadata, contexts = _rank_context(
            connection,
            Namespace(
                snapshot_day="20260924",
                strategy_version="2026.09.20.1",
                start_key="20250429",
            ),
        )

        self.assertTrue(metadata["provenance_available"])
        self.assertEqual(
            contexts[("opportunity", "600001")]["environment_permission"],
            "allowed",
        )
        self.assertEqual(
            contexts[("opportunity", "600001")]["market_components"]["sector"]["input_revision"],
            "sha256:market",
        )

    def test_stale_data_waits_for_refresh_even_when_other_gates_pass(self):
        snapshot, result = _candidate(data_date="2026-09-23")

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["eligibility_tier"], "waiting")
        self.assertEqual(features["data_quality"]["status"], "stale")
        self.assertIn("data_stale", features["eligibility_reasons"])

    def test_candidate_event_date_cannot_substitute_for_missing_snapshot_data_date(self):
        snapshot, result = _candidate()
        snapshot.pop("data_date")

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["eligibility_tier"], "waiting")
        self.assertEqual(features["data_quality"]["status"], "unknown")

    def test_missing_expected_session_does_not_assume_latest_data_is_current(self):
        snapshot, result = _candidate()

        features = build_candidate_ranking_features_v1(snapshot, "opportunity", result)

        self.assertEqual(features["eligibility_tier"], "waiting")
        self.assertEqual(features["data_quality"]["status"], "unknown")

    def test_forbidden_and_blocked_cannot_be_rescued_by_high_legacy_scores(self):
        snapshot, result = _candidate(permission="forbidden", plan_status="blocked")

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["eligibility_tier"], "blocked")
        self.assertEqual(features["legacy_scores"]["structure_score"], 95)
        self.assertNotIn("ranking_score", features)

    def test_calendar_age_uses_confirmation_date_and_session_index(self):
        snapshot, result = _candidate()
        facts = result["v2_state_model"]["facts"]
        facts["structure"] = {
            "fractals": {
                "latest_bottom": {
                    "date": "2026-09-18",
                    "analysis_date": "2026-09-22",
                    "price": 9.9,
                },
                "double_bottom_higher_low": True,
            }
        }
        sessions = ["2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
            calendar_session_index=build_calendar_session_index(sessions),
        )

        pivot = features["evidence"]["pivot_structure"]
        self.assertEqual(pivot["known_on"], "2026-09-22")
        self.assertEqual(pivot["age_sessions"], 2)
        self.assertTrue(pivot["double_bottom_higher_low"])

    def test_active_rectangle_alias_is_projected_once(self):
        snapshot, result = _candidate()
        result["v2_state_model"]["facts"]["structure"] = {
            "active_rectangle": {"available": True, "quality_score": 65, "width_pct": 20},
            "rectangle": {"available": True, "quality_score": 65, "width_pct": 20},
        }

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["evidence"]["active_range"]["source"], "structure.active_rectangle")
        self.assertEqual(features["evidence"]["active_range"]["quality_score"], 65)

    def test_attack_and_ignition_share_one_trigger_family(self):
        snapshot, result = _candidate()
        facts = result["v2_state_model"]["facts"]
        facts["trigger"] = {"attack_day": True, "ignition": {"triggered": True}}
        facts["setup"] = {"breakout_trigger": True}
        facts["structure"] = {"bear_trap_recovery": {"breakout_after_recovery": True}}

        features = build_candidate_ranking_features_v1(
            snapshot,
            "opportunity",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["evidence"]["entry_trigger_families"], ["attack", "breakout"])

    def test_risk_pool_watch_event_is_not_upgraded_to_risk_control(self):
        snapshot, result = _candidate(
            pool="risk",
            permission="watch_only",
            plan_status="",
            environment="unknown",
            state="top_fractal_observe",
            role="watch",
        )

        features = build_candidate_ranking_features_v1(
            snapshot,
            "risk",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["eligibility_tier"], "observe")

    def test_bottom_div_keeps_repair_semantics(self):
        snapshot, result = _candidate(
            pool="bottom_div",
            permission="watch_only",
            plan_status="",
            environment="unknown",
            state="repair_setup",
            role="watch",
        )

        features = build_candidate_ranking_features_v1(
            snapshot,
            "bottom_div",
            result,
            expected_session_date="2026-09-24",
        )

        self.assertEqual(features["eligibility_tier"], "repair_watch")


if __name__ == "__main__":
    unittest.main()
