import json
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.validate_scan_index import _indexed_candidates, _source_candidates
from scripts.archive_scan_snapshot_day import build_snapshot_day_archive
from stock_analyzer.scan_snapshot_archive import SnapshotArchiveError
from stock_analyzer.scan_candidate_shadow import compare_candidate_reads
from stock_analyzer.scan_index_store import (
    RANK_CONTEXT_SCOPE_LATEST_FRESH,
    RANK_CONTEXT_SCOPE_SNAPSHOT,
    SCAN_INDEX_SCHEMA_VERSION,
    ScanIndexStore,
    discover_scan_snapshot_files,
)
from stock_analyzer.scan_snapshot import snapshot_day_text
from stock_analyzer.scan_snapshot_storage import discover_snapshot_storage
from stock_analyzer.scan_planner import plan_scan_codes
from stock_analyzer.scan_rank_context_materializer import (
    materialize_workspace_rank_context,
)
from stock_analyzer.scan_rank_context import (
    RANK_CONTEXT_SCHEMA_VERSION,
    RANKING_POLICY_VERSION,
    rank_context_candidates,
)
from stock_analyzer.versioning import SCAN_STRATEGY_VERSION


def _snapshot(*, code="600001", snapshot_day="20260922", priority=180.0):
    return {
        "version": 1,
        "strategy_version": SCAN_STRATEGY_VERSION,
        "data_adjust": "qfq",
        "code": code,
        "name": "样本A",
        "sector": "半导体",
        "concepts": ["存储芯片", "国产替代"],
        "snapshot_day": snapshot_day,
        "data_date": "2026-09-22",
        "calendar_id": "XSHG",
        "calendar_revision": "sha256:calendar",
        "calendar_evidence_level": "provider",
        "rows": 342,
        "computed_scan_types": ["opportunity", "risk", "bottom_div"],
        "results": {
            "opportunity": {
                "code": code,
                "name": "样本A",
                "sector": "半导体",
                "concepts": ["存储芯片", "国产替代"],
                "event_date": "2026-09-22",
                "signal_key": "v2_breakout",
                "v2_signal": "C突",
                "v2_state": "trigger_plan_ready",
                "v2_permission": "breakout_allowed",
                "v2_plan_status": "ready",
                "v2_priority_score": priority,
                "v2_priority_group": "trade_ready",
                "reason": "突破成立，计划校验通过。",
                "candidate_missing_confirmations": ["次日价格确认"],
                "candidate_invalidation_price": 9.8,
                "price": 10.5,
                "rank_score": 88,
                "confirm_score": 5,
                "risk_score": 1,
                "requires_trade_plan": True,
                "requires_stop_loss": True,
            },
            "risk": {
                "code": code,
                "name": "样本A",
                "event_date": "2026-09-22",
                "signal_key": "v2_exit_risk",
                "v2_signal": "C风",
                "v2_state": "risk_control",
                "v2_permission": "forbidden",
                "v2_priority_score": 120,
                "reason": "风险条件成立。",
                "price": 10.5,
                "risk_score": 5,
            },
        },
    }


def _rank_fingerprint(revision):
    return {
        "revision": revision,
        "schema_version": RANK_CONTEXT_SCHEMA_VERSION,
        "ranking_policy_version": RANKING_POLICY_VERSION,
    }


class ScanIndexStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.snapshot_path = self.root / "600001_20250429_20260922.json"
        self.database_path = self.root / "scan_index.sqlite3"
        self.store = ScanIndexStore(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_snapshot(self, payload):
        self.snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_indexes_candidate_summaries_without_copying_full_facts(self):
        payload = _snapshot()
        payload["results"]["opportunity"]["v2_state_model"] = {
            "facts": {"normalized_bars": [{"close": 10.5}] * 1000}
        }
        self._write_snapshot(payload)

        stats = self.store.index_snapshot_files([self.snapshot_path], reset=True)

        self.assertEqual(stats.indexed, 1)
        self.assertEqual(stats.candidates, 2)
        candidates = self.store.query_candidates(pool="opportunity")
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["code"], "600001")
        self.assertEqual(candidate["signal_key"], "v2_breakout")
        self.assertEqual(candidate["calendar_id"], "XSHG")
        self.assertEqual(candidate["calendar_revision"], "sha256:calendar")
        self.assertEqual(candidate["reason_tags"], ["plan_ready", "c_breakout"])
        self.assertEqual(candidate["missing_confirmations"], ["次日价格确认"])
        self.assertEqual(candidate["concepts"], ["存储芯片", "国产替代"])
        self.assertNotIn("facts", candidate)
        self.assertNotIn("v2_state_model", candidate)
        self.assertTrue(candidate["requires_trade_plan"])

        by_concept = self.store.query_candidates(
            pool="opportunity",
            concept="存储芯片",
        )
        by_reason = self.store.query_candidates(
            pool="opportunity",
            reason="plan_ready",
        )
        self.assertEqual([item["code"] for item in by_concept], ["600001"])
        self.assertEqual([item["code"] for item in by_reason], ["600001"])
        self.assertTrue(self.store.status()["reason_tags_complete"])

    def test_validator_joins_public_candidates_without_snapshot_paths(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        args = Namespace(
            snapshot_dir=self.root,
            start_key="20250429",
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            pools=None,
        )

        source = _source_candidates(args)
        indexed = _indexed_candidates(args, self.store)

        self.assertEqual(set(source), set(indexed))
        self.assertEqual(set(indexed), {("600001", "opportunity"), ("600001", "risk")})
        self.assertNotIn("snapshot_path", indexed[("600001", "opportunity")])

    def test_scan_history_rows_are_aggregated_from_manifest_and_candidates(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)

        rows = self.store.scan_history_rows(
            start_key="20250429",
            scan_types=("opportunity", "risk", "bottom_div"),
            current_strategy_version=SCAN_STRATEGY_VERSION,
            current_data_adjust="qfq",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["snapshot_day"], "20260922")
        self.assertEqual(rows[0]["snapshot_count"], 1)
        self.assertEqual(rows[0]["current_strategy_count"], 1)
        self.assertEqual(rows[0]["pool_counts"]["opportunity"], 1)
        self.assertEqual(rows[0]["pool_counts"]["risk"], 1)
        self.assertEqual(rows[0]["pool_counts"]["bottom_div"], 0)

    def test_v4_initialization_repairs_legacy_candidate_schema_versions(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        with self.store._connect() as connection:
            connection.execute("UPDATE candidate_summaries SET schema_version = 1")

        self.store.initialize()

        candidates = self.store.query_candidates(pool="opportunity")
        self.assertEqual(candidates[0]["schema_version"], 2)
        self.assertEqual(candidates[0]["calendar_id"], "XSHG")

    def test_shadow_comparison_separates_semantics_from_dynamic_ranking(self):
        workspace = [
            {
                "code": "600001",
                "event_date": "2026-09-22",
                "signal_key": "v2_breakout",
                "v2_signal": "C突",
                "v2_state": "entry_breakout",
                "v2_permission": "breakout_allowed",
                "v2_plan_status": "ready",
                "candidate_missing_confirmations": [],
                "candidate_invalidation_price": 9.8,
                "requires_trade_plan": True,
                "requires_stop_loss": True,
                "v2_priority_score": 620,
                "v2_priority_group": "trade_ready",
                "final_score": 58,
            },
            {
                "code": "600002",
                "event_date": "2026-09-22",
                "signal_key": "v2_structure_candidate",
                "v2_signal": "C候",
                "v2_state": "structure_candidate",
                "v2_permission": "structure_only",
                "candidate_missing_confirmations": ["V2 触发事实"],
                "candidate_invalidation_price": 8.8,
                "v2_priority_score": 180,
                "v2_priority_group": "structure_watch",
                "final_score": 20,
            },
        ]
        indexed = [
            {
                "code": "600002",
                "event_date": "2026-09-22",
                "signal_key": "v2_structure_candidate",
                "signal_label": "C候",
                "state": "structure_candidate",
                "permission": "structure_only",
                "missing_confirmations": ["V2 触发事实"],
                "invalidation_price": 8.8,
                "priority_score": 176,
                "priority_group": "structure_watch",
                "final_score": 18,
            },
            {
                "code": "600001",
                "event_date": "2026-09-22",
                "signal_key": "v2_breakout",
                "signal_label": "C突",
                "state": "entry_breakout",
                "permission": "breakout_allowed",
                "plan_status": "ready",
                "missing_confirmations": [],
                "invalidation_price": 9.8,
                "requires_trade_plan": True,
                "requires_stop_loss": True,
                "priority_score": 190,
                "priority_group": "structure_watch",
                "final_score": 25,
            },
        ]

        comparison = compare_candidate_reads(workspace, indexed)

        self.assertTrue(comparison["hard_gate_pass"])
        self.assertFalse(comparison["ordering"]["exact_match"])
        self.assertEqual(comparison["hard_fields"]["mismatch_count"], 0)
        self.assertEqual(comparison["ranking_fields"]["mismatch_count"], 2)

    def test_shadow_comparison_fails_on_decision_contract_drift(self):
        workspace = [{
            "code": "600001",
            "event_date": "2026-09-22",
            "signal_key": "v2_breakout",
            "v2_permission": "breakout_allowed",
        }]
        indexed = [{
            "code": "600001",
            "event_date": "2026-09-22",
            "signal_key": "v2_breakout",
            "permission": "structure_only",
        }]

        comparison = compare_candidate_reads(workspace, indexed)

        self.assertFalse(comparison["hard_gate_pass"])
        self.assertEqual(
            comparison["hard_fields"]["mismatch_fields"],
            {"permission": 1},
        )

    def test_candidate_summary_preserves_explicit_false_and_empty_values(self):
        payload = _snapshot()
        result = payload["results"]["opportunity"]
        result["candidate_missing_confirmations"] = []
        result["requires_trade_plan"] = False
        result["requires_stop_loss"] = False
        result["v2_state_model"] = {
            "candidate_missing_confirmations": ["状态层确认"],
            "requires_trade_plan": True,
            "requires_stop_loss": True,
            "v2_permission_model": {
                "required_confirmations": ["许可层确认"],
            },
        }

        self._write_snapshot(payload)
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        candidate = self.store.query_candidates(pool="opportunity")[0]

        self.assertEqual(candidate["missing_confirmations"], [])
        self.assertFalse(candidate["requires_trade_plan"])
        self.assertFalse(candidate["requires_stop_loss"])

    def test_materialized_rank_context_orders_without_overwriting_base_score(self):
        second_path = self.root / "600002_20250429_20260922.json"
        self._write_snapshot(_snapshot(priority=180.0))
        second_path.write_text(
            json.dumps(
                _snapshot(code="600002", priority=170.0),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.store.index_snapshot_files(
            [self.snapshot_path, second_path],
            reset=True,
        )
        records = []
        for code, opportunity_score in (("600001", 800.0), ("600002", 900.0)):
            records.extend([
                {
                    "pool": "opportunity",
                    "code": code,
                    "event_date": "2026-09-22",
                    "context_priority_score": opportunity_score,
                    "context_priority_group": "context_ready",
                    "context_final_score": opportunity_score / 10,
                    "environment_permission": "allowed",
                },
                {
                    "pool": "risk",
                    "code": code,
                    "event_date": "2026-09-22",
                    "context_priority_score": 500.0,
                    "context_priority_group": "risk_control",
                    "context_final_score": 50.0,
                },
            ])

        status = self.store.materialize_rank_context(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            source_fingerprint=_rank_fingerprint("fixture-v1"),
            candidates=records,
            computed_at="2026-09-23T00:00:00+00:00",
        )
        base_page = self.store.query_candidate_page(
            pool="opportunity",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
        )
        context_page = self.store.query_candidate_page(
            pool="opportunity",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            rank_mode="contextual",
        )

        self.assertTrue(status["available"])
        self.assertEqual(status["overlay_count"], 4)
        self.assertEqual(
            [item["code"] for item in base_page["results"]],
            ["600001", "600002"],
        )
        self.assertEqual(
            [item["code"] for item in context_page["results"]],
            ["600002", "600001"],
        )
        self.assertEqual(context_page["ranking"]["mode"], "contextual")
        self.assertTrue(context_page["ranking"]["context_applied"])
        self.assertEqual(context_page["results"][0]["priority_score"], 170.0)
        self.assertEqual(
            context_page["results"][0]["rank_context"]["priority_score"],
            900.0,
        )
        self.assertEqual(
            context_page["results"][0]["rank_context"]["environment_permission"],
            "allowed",
        )
        self.assertIsNone(context_page["results"][0]["rank_context"]["sector_score"])
        self.assertEqual(context_page["results"][0]["rank_context"]["market_context"], {})

    def test_rank_context_rejects_old_policy_revision(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        records = [
            {
                "pool": pool,
                "code": "600001",
                "event_date": "2026-09-22",
                "context_priority_score": score,
                "context_priority_group": "legacy",
                "context_final_score": score,
            }
            for pool, score in (("opportunity", 800.0), ("risk", 500.0))
        ]
        self.store.materialize_rank_context(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            source_fingerprint={
                "schema_version": RANK_CONTEXT_SCHEMA_VERSION - 1,
                "ranking_policy_version": "legacy-market-resonance",
            },
            candidates=records,
        )

        status = self.store.rank_context_status(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
        )
        page = self.store.query_candidate_page(
            pool="opportunity",
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            rank_mode="contextual",
        )

        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "ranking_policy_mismatch")
        self.assertEqual(page["ranking"]["mode"], "snapshot_local")
        self.assertEqual(page["ranking"]["fallback_reason"], "ranking_policy_mismatch")

    def test_rank_context_rejects_legacy_factors_even_with_current_policy_tag(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        records = [
            {
                "pool": pool,
                "code": "600001",
                "event_date": "2026-09-22",
                "context_priority_score": score,
                "context_priority_group": "invalid-current-policy",
                "context_final_score": score,
                "sector_score": 90,
                "market_context": {"sector": {"as_of": "2026-09-22"}},
            }
            for pool, score in (("opportunity", 800.0), ("risk", 500.0))
        ]
        self.store.materialize_rank_context(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            source_fingerprint=_rank_fingerprint("invalid-current-policy"),
            candidates=records,
        )

        status = self.store.rank_context_status(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
        )

        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "ranking_policy_violation")

    def test_rank_context_projection_keeps_only_macro_permission(self):
        candidates = rank_context_candidates(
            {
                "pools": {
                    "opportunity": {
                        "results": [{
                            "code": "600001",
                            "event_date": "2026-09-22",
                            "snapshot_strategy_version": SCAN_STRATEGY_VERSION,
                            "v2_priority_score": 700,
                            "v2_priority_group": "trade_ready",
                            "v2_environment_permission": "allowed",
                            "sector_market_source": "tencent_direct",
                            "sector_market_index_code": "BK001",
                            "sector_market_latest_date": "2026-09-22",
                            "sector_market_boost": 2.5,
                            "sector_market_score": 68,
                            "sector_market_cache_stale": False,
                        }],
                    },
                },
            },
            strategy_version=SCAN_STRATEGY_VERSION,
        )

        self.assertEqual(candidates[0]["environment_permission"], "allowed")
        self.assertIsNone(candidates[0]["sector_score"])
        self.assertIsNone(candidates[0]["concept_score"])
        self.assertIsNone(candidates[0]["market_boost"])
        self.assertEqual(candidates[0]["market_context"], {})

    def test_rank_context_falls_back_after_candidate_reindex(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        records = [
            {
                "pool": pool,
                "code": "600001",
                "event_date": "2026-09-22",
                "context_priority_score": score,
                "context_priority_group": "fixture",
                "context_final_score": score,
            }
            for pool, score in (("opportunity", 800.0), ("risk", 500.0))
        ]
        self.store.materialize_rank_context(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            source_fingerprint=_rank_fingerprint("fixture-v1"),
            candidates=records,
        )

        self._write_snapshot(_snapshot(priority=181.0))
        self.store.index_snapshot_files([self.snapshot_path], force=True)
        status = self.store.rank_context_status(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
        )
        page = self.store.query_candidate_page(
            pool="opportunity",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            rank_mode="contextual",
        )

        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "incomplete")
        self.assertEqual(page["ranking"]["requested_mode"], "contextual")
        self.assertEqual(page["ranking"]["mode"], "snapshot_local")
        self.assertEqual(page["ranking"]["fallback_reason"], "incomplete")
        self.assertNotIn("rank_context", page["results"][0])

    def test_rank_context_replacement_prunes_stale_revision(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        records = [
            {
                "pool": pool,
                "code": "600001",
                "event_date": "2026-09-22",
                "context_priority_score": score,
                "context_priority_group": "fixture",
                "context_final_score": score,
            }
            for pool, score in (("opportunity", 800.0), ("risk", 500.0))
        ]
        first = self.store.materialize_rank_context(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            source_fingerprint=_rank_fingerprint("fixture-v1"),
            candidates=records,
        )
        records[0]["context_priority_score"] = 801.0
        second = self.store.materialize_rank_context(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            source_fingerprint=_rank_fingerprint("fixture-v2"),
            candidates=records,
        )
        status = self.store.status()

        self.assertNotEqual(first["context_revision"], second["context_revision"])
        self.assertEqual(status["rank_context_run_count"], 1)
        self.assertEqual(status["rank_context_head_count"], 1)
        self.assertEqual(status["rank_context_candidate_count"], 2)

    def test_workspace_rank_context_materializer_reuses_unchanged_revision(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        workspace = {
            "history_snapshot_day": "2026-09-22",
            "latest_snapshot_day": "2026-09-22",
            "pools": {
                pool: {
                    "results": [{
                        "code": "600001",
                        "event_date": "2026-09-22",
                        "snapshot_strategy_version": SCAN_STRATEGY_VERSION,
                        "v2_priority_score": score,
                        "v2_priority_group": "fixture",
                        "final_score": score / 10,
                    }]
                }
                for pool, score in (("opportunity", 800.0), ("risk", 500.0))
            },
        }
        with (
            patch(
                "stock_analyzer.scan_rank_context_materializer.collect_scan_workspace",
                return_value=workspace,
            ) as collect,
            patch(
                "stock_analyzer.scan_rank_context_materializer.scan_workspace_dependency_fingerprint",
                return_value={"revision": "fixture-v1"},
            ),
        ):
            first = materialize_workspace_rank_context(
                self.store,
                start_date="2025-04-29",
                strategy_version=SCAN_STRATEGY_VERSION,
            )
            second = materialize_workspace_rank_context(
                self.store,
                start_date="2025-04-29",
                strategy_version=SCAN_STRATEGY_VERSION,
            )

        self.assertEqual(first["status"], "materialized")
        self.assertEqual(second["status"], "reused")
        self.assertTrue(second["rank_context"]["available"])
        self.assertEqual(collect.call_count, 1)

    def test_rank_context_scopes_match_full_and_latest_fresh_populations(self):
        today = snapshot_day_text()
        stale_date = (datetime.strptime(today, "%Y%m%d") - timedelta(days=30)).strftime("%Y-%m-%d")
        fresh_payload = _snapshot(code="600001", snapshot_day=today)
        fresh_payload["data_date"] = f"{today[:4]}-{today[4:6]}-{today[6:8]}"
        stale_payload = _snapshot(code="600002", snapshot_day=today)
        stale_payload["data_date"] = stale_date
        fresh_data_date = [fresh_payload["data_date"]]
        fresh_path = self.root / f"600001_20250429_{today}.json"
        stale_path = self.root / f"600002_20250429_{today}.json"
        fresh_path.write_text(json.dumps(fresh_payload, ensure_ascii=False), encoding="utf-8")
        stale_path.write_text(json.dumps(stale_payload, ensure_ascii=False), encoding="utf-8")
        with (
            patch("stock_analyzer.scan_snapshot.market_calendar_context", return_value={"is_session": False}),
            patch(
                "stock_analyzer.scan_snapshot.is_recent_snapshot",
                side_effect=lambda snapshot: snapshot.get("data_date") == fresh_data_date[0],
            ),
        ):
            self.store.index_snapshot_files([fresh_path, stale_path], reset=True)

            def records(codes, score_base):
                return [
                    {
                        "pool": pool,
                        "code": code,
                        "event_date": "2026-09-22",
                        "context_priority_score": score_base + index,
                        "context_priority_group": "fixture",
                        "context_final_score": score_base / 10,
                    }
                    for index, code in enumerate(codes)
                    for pool in ("opportunity", "risk")
                ]

            full = self.store.materialize_rank_context(
                snapshot_day=today,
                strategy_version=SCAN_STRATEGY_VERSION,
                start_key="20250429",
                source_fingerprint=_rank_fingerprint("full"),
                candidates=records(["600001", "600002"], 800),
                context_scope=RANK_CONTEXT_SCOPE_SNAPSHOT,
            )
            latest = self.store.materialize_rank_context(
                snapshot_day=today,
                strategy_version=SCAN_STRATEGY_VERSION,
                start_key="20250429",
                source_fingerprint=_rank_fingerprint("latest"),
                candidates=records(["600001"], 900),
                context_scope=RANK_CONTEXT_SCOPE_LATEST_FRESH,
            )

            latest_page = self.store.query_candidate_page(
                pool="opportunity",
                snapshot_day=today,
                strategy_version=SCAN_STRATEGY_VERSION,
                start_key="20250429",
                rank_mode="contextual",
                recent_only=True,
            )
            snapshot_page = self.store.query_candidate_page(
                pool="opportunity",
                snapshot_day=today,
                strategy_version=SCAN_STRATEGY_VERSION,
                start_key="20250429",
                rank_mode="contextual",
                recent_only=False,
            )

            self.assertTrue(full["available"])
            self.assertTrue(latest["available"])
            self.assertNotEqual(full["run_key"], latest["run_key"])
            self.assertEqual(full["candidate_count"], 4)
            self.assertEqual(latest["candidate_count"], 2)
            self.assertEqual(latest_page["ranking"]["mode"], "contextual")
            self.assertEqual([row["code"] for row in latest_page["results"]], ["600001"])
            self.assertEqual(latest_page["results"][0]["rank_context"]["priority_score"], 900)
            self.assertEqual(
                {row["code"] for row in snapshot_page["results"]},
                {"600001", "600002"},
            )

            # Keep the fresh population size constant while swapping its member.
            fresh_data_date[0] = stale_date

            latest_status = self.store.rank_context_status(
                snapshot_day=today,
                strategy_version=SCAN_STRATEGY_VERSION,
                start_key="20250429",
                context_scope=RANK_CONTEXT_SCOPE_LATEST_FRESH,
            )
            self.assertFalse(latest_status["available"])
            self.assertFalse(latest_status["scope_matches"])
            self.assertEqual(latest_status["missing_overlay_count"], 2)
            self.assertEqual(latest_status["out_of_scope_overlay_count"], 2)

    def test_latest_fresh_materializer_uses_unpinned_fresh_workspace(self):
        today = snapshot_day_text()
        fresh_payload = _snapshot(snapshot_day=today)
        fresh_payload["data_date"] = f"{today[:4]}-{today[4:6]}-{today[6:8]}"
        fresh_path = self.root / f"600001_20250429_{today}.json"
        fresh_path.write_text(json.dumps(fresh_payload, ensure_ascii=False), encoding="utf-8")
        with patch("stock_analyzer.scan_snapshot.market_calendar_context", return_value={"is_session": False}):
            self.store.index_snapshot_files([fresh_path], reset=True)
            workspace = {
                "history_snapshot_day": "",
                "latest_snapshot_day": today,
                "pools": {
                    pool: {
                        "results": [{
                            "code": "600001",
                            "event_date": "2026-09-22",
                            "snapshot_strategy_version": SCAN_STRATEGY_VERSION,
                            "v2_priority_score": score,
                            "v2_priority_group": "fixture",
                            "final_score": score / 10,
                        }]
                    }
                    for pool, score in (("opportunity", 800), ("risk", 500))
                },
            }
            with (
                patch(
                    "stock_analyzer.scan_rank_context_materializer.collect_scan_workspace",
                    return_value=workspace,
                ) as collect,
                patch(
                    "stock_analyzer.scan_rank_context_materializer.scan_workspace_dependency_fingerprint",
                    return_value={"revision": "fresh-fixture"},
                ),
            ):
                result = materialize_workspace_rank_context(
                    self.store,
                    start_date="2025-04-29",
                    snapshot_day=today,
                    strategy_version=SCAN_STRATEGY_VERSION,
                    context_scope=RANK_CONTEXT_SCOPE_LATEST_FRESH,
                )

        self.assertTrue(result["rank_context"]["available"])
        self.assertEqual(result["context_scope"], RANK_CONTEXT_SCOPE_LATEST_FRESH)
        self.assertIsNone(collect.call_args.kwargs["snapshot_day"])
        self.assertTrue(collect.call_args.kwargs["latest_only"])

    def test_latest_fresh_materializer_publishes_empty_scope_without_valid_rows(self):
        today = snapshot_day_text()
        payload = _snapshot(snapshot_day=today)
        path = self.root / f"600001_20250429_{today}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with (
            patch("stock_analyzer.scan_snapshot.is_recent_snapshot", return_value=False),
            patch(
                "stock_analyzer.scan_rank_context_materializer.scan_workspace_dependency_fingerprint",
                return_value={"revision": "empty-fresh-fixture"},
            ),
            patch(
                "stock_analyzer.scan_rank_context_materializer.collect_scan_workspace",
                side_effect=AssertionError("empty latest scope must not load a workspace"),
            ),
        ):
            self.store.index_snapshot_files([path], reset=True)
            result = materialize_workspace_rank_context(
                self.store,
                start_date="2025-04-29",
                snapshot_day=today,
                strategy_version=SCAN_STRATEGY_VERSION,
                context_scope=RANK_CONTEXT_SCOPE_LATEST_FRESH,
            )

        self.assertTrue(result["rank_context"]["available"])
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["rank_context"]["overlay_count"], 0)

    def test_unchanged_file_is_skipped_and_force_replaces_rows(self):
        self._write_snapshot(_snapshot(priority=180.0))
        first = self.store.index_snapshot_files([self.snapshot_path], reset=True)
        second = self.store.index_snapshot_files([self.snapshot_path])

        self.assertEqual(first.indexed, 1)
        self.assertEqual(second.skipped, 1)

        payload = _snapshot(priority=250.0)
        payload["results"].pop("risk")
        self._write_snapshot(payload)
        third = self.store.index_snapshot_files([self.snapshot_path], force=True)

        self.assertEqual(third.indexed, 1)
        self.assertEqual(third.candidates, 1)
        opportunity = self.store.query_candidates(pool="opportunity")[0]
        self.assertEqual(opportunity["priority_score"], 250.0)
        self.assertEqual(self.store.query_candidates(pool="risk"), [])
        self.assertEqual(self.store.status()["candidate_count"], 1)

    def test_query_defaults_to_latest_day_and_supports_filters(self):
        older_path = self.root / "600002_20250429_20260921.json"
        older_path.write_text(
            json.dumps(_snapshot(code="600002", snapshot_day="20260921"), ensure_ascii=False),
            encoding="utf-8",
        )
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([older_path, self.snapshot_path], reset=True)

        latest = self.store.query_candidates(pool="opportunity")
        self.assertEqual([item["code"] for item in latest], ["600001"])
        older = self.store.query_candidates(
            pool="opportunity",
            snapshot_day="20260921",
            query="600002",
        )
        self.assertEqual([item["code"] for item in older], ["600002"])
        self.assertEqual(self.store.latest_snapshot_day(), "20260922")

    def test_latest_run_without_pool_candidates_does_not_reuse_older_candidates(self):
        older_path = self.root / "600002_20250429_20260921.json"
        older_path.write_text(
            json.dumps(_snapshot(code="600002", snapshot_day="20260921"), ensure_ascii=False),
            encoding="utf-8",
        )
        latest = _snapshot(snapshot_day="20260922")
        latest["results"].pop("opportunity")
        self._write_snapshot(latest)
        self.store.index_snapshot_files([older_path, self.snapshot_path], reset=True)

        candidates = self.store.query_candidates(
            pool="opportunity",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
        )

        self.assertEqual(candidates, [])

    def test_candidate_page_reports_filtered_and_pool_counts(self):
        second_path = self.root / "600002_20250429_20260922.json"
        self._write_snapshot(_snapshot())
        second = _snapshot(code="600002", priority=170.0)
        second["name"] = "样本B"
        second["results"]["opportunity"]["name"] = "样本B"
        second["results"]["opportunity"]["concepts"] = ["机器人概念"]
        second_path.write_text(json.dumps(second, ensure_ascii=False), encoding="utf-8")
        self.store.index_snapshot_files([self.snapshot_path, second_path], reset=True)

        page = self.store.query_candidate_page(
            pool="opportunity",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            concept="机器人概念",
            limit=1,
        )

        self.assertEqual(page["source"], "sqlite_index")
        self.assertEqual(page["schema_version"], SCAN_INDEX_SCHEMA_VERSION)
        self.assertEqual(page["ranking"]["mode"], "snapshot_local")
        self.assertFalse(page["ranking"]["context_applied"])
        self.assertEqual(page["count"], 1)
        self.assertEqual(page["pool_count"], 2)
        self.assertEqual(page["loaded_count"], 1)
        self.assertFalse(page["has_more"])
        self.assertEqual([item["code"] for item in page["results"]], ["600002"])
        self.assertEqual(page["snapshot_day"], "20260922")

    def test_candidate_search_treats_like_wildcards_as_literal_text(self):
        second_path = self.root / "600002_20250429_20260922.json"
        first = _snapshot()
        first["name"] = "样本_百分号%"
        first["results"]["opportunity"]["name"] = "样本_百分号%"
        self._write_snapshot(first)
        second_path.write_text(
            json.dumps(_snapshot(code="600002"), ensure_ascii=False),
            encoding="utf-8",
        )
        self.store.index_snapshot_files([self.snapshot_path, second_path], reset=True)

        percent = self.store.query_candidate_page(pool="opportunity", query="%")
        underscore = self.store.query_candidate_page(pool="opportunity", query="_")

        self.assertEqual([item["code"] for item in percent["results"]], ["600001"])
        self.assertEqual([item["code"] for item in underscore["results"]], ["600001"])

    def test_strategy_filter_uses_latest_day_for_that_strategy(self):
        current_path = self.root / "600002_20250429_20260921.json"
        current_path.write_text(
            json.dumps(_snapshot(code="600002", snapshot_day="20260921"), ensure_ascii=False),
            encoding="utf-8",
        )
        legacy = _snapshot(snapshot_day="20260922")
        legacy["strategy_version"] = "legacy-strategy"
        self._write_snapshot(legacy)
        self.store.index_snapshot_files([current_path, self.snapshot_path], reset=True)

        candidates = self.store.query_candidates(
            pool="opportunity",
            strategy_version=SCAN_STRATEGY_VERSION,
        )

        self.assertEqual([item["code"] for item in candidates], ["600002"])
        self.assertEqual(candidates[0]["snapshot_day"], "20260921")

    def test_start_key_keeps_history_windows_separate(self):
        alternate_path = self.root / "600001_20260101_20260922.json"
        self._write_snapshot(_snapshot(priority=180.0))
        alternate_path.write_text(
            json.dumps(_snapshot(priority=300.0), ensure_ascii=False),
            encoding="utf-8",
        )
        self.store.index_snapshot_files(
            [self.snapshot_path, alternate_path],
            reset=True,
        )

        default_window = self.store.query_candidates(
            pool="opportunity",
            start_key="20250429",
        )
        alternate_window = self.store.query_candidates(
            pool="opportunity",
            start_key="20260101",
        )

        self.assertEqual(len(default_window), 1)
        self.assertEqual(default_window[0]["priority_score"], 180.0)
        self.assertEqual(default_window[0]["start_key"], "20250429")
        self.assertEqual(len(alternate_window), 1)
        self.assertEqual(alternate_window[0]["priority_score"], 300.0)
        self.assertEqual(self.store.status()["run_count"], 2)

    def test_malformed_snapshot_is_recorded_without_candidates(self):
        self.snapshot_path.write_text("{not-json", encoding="utf-8")

        stats = self.store.index_snapshot_files([self.snapshot_path], reset=True)

        self.assertEqual(stats.failed, 1)
        status = self.store.status()
        self.assertEqual(status["schema_version"], SCAN_INDEX_SCHEMA_VERSION)
        self.assertEqual(status["invalid_snapshot_count"], 1)
        self.assertEqual(status["candidate_count"], 0)
        self.assertEqual(status["build_scope"], "partial")
        self.assertFalse(status["index_complete"])

    def test_bad_candidate_in_one_snapshot_does_not_abort_following_files(self):
        import copy

        broken_path = self.root / "600002_20250429_20260922.json"
        broken = copy.deepcopy(_snapshot(code="600002"))
        broken["version"] = "not-an-integer"
        broken_path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        self._write_snapshot(_snapshot())

        stats = self.store.index_snapshot_files(
            [broken_path, self.snapshot_path],
            reset=True,
        )

        self.assertEqual(stats.failed, 1)
        self.assertEqual(stats.indexed, 1)
        self.assertEqual(self.store.status()["invalid_snapshot_count"], 1)
        self.assertEqual(
            [row["code"] for row in self.store.query_candidates(pool="opportunity")],
            ["600001"],
        )

    def test_index_migrations_are_idempotent_and_initialization_is_serialized(self):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(lambda _: ScanIndexStore(self.database_path).initialize(), range(6)))

        self.store.initialize()
        with self.store._connect() as connection:
            self.store._migrate_v5_to_v6(connection)
            self.store._migrate_v5_to_v6(connection)
            self.store._migrate_v6_to_v7(connection)
            self.store._migrate_v6_to_v7(connection)
            self.store._migrate_v7_to_v8(connection)
            self.store._migrate_v7_to_v8(connection)
            self.store._migrate_v8_to_v9(connection)
            self.store._migrate_v8_to_v9(connection)
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(candidate_rank_contexts)"
                ).fetchall()
            }
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            manifest_columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(snapshot_manifest)"
                ).fetchall()
            }
            manifest_indexes = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA index_list(snapshot_manifest)"
                ).fetchall()
            }

        self.assertEqual(version, SCAN_INDEX_SCHEMA_VERSION)
        self.assertIn("environment_permission", columns)
        self.assertIn("market_context_json", columns)
        self.assertIn("computed_scan_types_json", manifest_columns)
        self.assertIn("storage_tier", manifest_columns)
        self.assertIn("archive_path", manifest_columns)
        self.assertIn("idx_snapshot_manifest_planning", manifest_indexes)
        self.assertIn("idx_snapshot_manifest_storage", manifest_indexes)

    def test_candidate_summary_rejects_non_finite_and_boolean_numbers(self):
        from stock_analyzer.candidate_read_model import CandidateSummary

        snapshot = _snapshot()
        opportunity = snapshot["results"]["opportunity"]
        opportunity["price"] = float("nan")
        opportunity["v2_priority_score"] = float("inf")
        opportunity["rank_score"] = 91

        summary = CandidateSummary.from_snapshot(snapshot, "opportunity")

        self.assertIsNone(summary.price)
        self.assertEqual(summary.priority_score, 91.0)
        self.assertIsNone(CandidateSummary.from_snapshot(
            {**snapshot, "results": {"opportunity": {**opportunity, "price": True}}},
            "opportunity",
        ).price)

    def test_full_build_scope_requires_explicit_complete_rebuild_record(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)

        partial_status = self.store.status()
        self.assertEqual(partial_status["build_scope"], "partial")
        self.assertFalse(partial_status["index_complete"])

        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
            completed_at="2026-09-23T00:00:00+00:00",
        )

        full_status = self.store.status()
        self.assertEqual(full_status["build_scope"], "full")
        self.assertTrue(full_status["index_complete"])
        self.assertEqual(full_status["full_rebuild_source_snapshot_count"], 1)
        self.assertEqual(
            full_status["full_rebuild_source_directory"],
            str(self.root.resolve()),
        )
        self.assertEqual(
            full_status["full_rebuild_completed_at"],
            "2026-09-23T00:00:00+00:00",
        )

    def test_snapshot_cache_fingerprint_advances_with_indexed_revision(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )

        first = self.store.cache_fingerprint(self.root)
        changed = _snapshot()
        changed["results"]["opportunity"]["price"] = 11.0
        self.snapshot_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        self.store.index_snapshot_files([self.snapshot_path], force=True)
        pending = self.store.cache_fingerprint(self.root)
        reconciliation = self.store.reconcile_source_directory(self.root)
        second = self.store.cache_fingerprint(self.root)

        self.assertTrue(first["available"])
        self.assertFalse(pending["available"])
        self.assertTrue(reconciliation["synchronized"])
        self.assertTrue(second["available"])
        self.assertNotEqual(first["revision"], second["revision"])

    def test_incremental_bootstrap_is_partial_but_preserves_existing_full_scope(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path])
        self.assertEqual(self.store.status()["build_scope"], "partial")

        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        self.store.index_snapshot_files([self.snapshot_path])

        self.assertEqual(self.store.status()["build_scope"], "full")
        self.assertTrue(self.store.status()["index_complete"])

    def test_reconcile_removes_deleted_manifest_rows_and_advances_source_sync(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        self.snapshot_path.unlink()

        reconciliation = self.store.reconcile_source_directory(self.root)
        status = self.store.status()

        self.assertTrue(reconciliation["synchronized"])
        self.assertEqual(reconciliation["deleted_manifest_count"], 1)
        self.assertEqual(status["snapshot_count"], 0)
        self.assertEqual(status["source_sync_snapshot_count"], 0)
        self.assertTrue(status["index_complete"])

    def test_reconcile_preserves_archived_snapshot_after_active_source_moves(self):
        self._write_snapshot(_snapshot())
        archive_dir = self.root / "archives"
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        build_snapshot_day_archive(self.root, archive_dir, "20260922")
        self.snapshot_path.unlink()

        reconciliation = self.store.reconcile_source_directory(
            self.root,
            archive_directory=archive_dir,
        )
        status = self.store.status()
        reference = self.store.get_candidate_reference(
            pool="opportunity",
            code="600001",
            snapshot_day="20260922",
            start_key="20250429",
        )

        self.assertTrue(reconciliation["synchronized"])
        self.assertEqual(reconciliation["deleted_manifest_count"], 0)
        self.assertEqual(reconciliation["archive_snapshot_count"], 1)
        self.assertEqual(status["snapshot_count"], 1)
        self.assertEqual(status["active_snapshot_count"], 0)
        self.assertEqual(status["archive_snapshot_count"], 1)
        self.assertTrue(status["index_complete"])
        self.assertEqual(reference["storage_tier"], "archive")
        self.assertTrue(Path(reference["archive_path"]).is_file())

    def test_full_index_can_be_rebuilt_from_archive_only(self):
        self._write_snapshot(_snapshot())
        archive_dir = self.root / "archives"
        build_snapshot_day_archive(self.root, archive_dir, "20260922")
        self.snapshot_path.unlink()
        records = discover_snapshot_storage(self.root, archive_dir)
        rebuilt = ScanIndexStore(self.root / "rebuilt.sqlite3")

        stats = rebuilt.index_snapshot_records(records, reset=True)
        rebuilt.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        reconciliation = rebuilt.reconcile_source_directory(
            self.root,
            archive_directory=archive_dir,
        )

        self.assertEqual(stats.failed, 0)
        self.assertEqual(stats.indexed, 1)
        self.assertEqual(stats.candidates, 2)
        self.assertTrue(reconciliation["synchronized"])
        self.assertEqual(rebuilt.status()["archive_snapshot_count"], 1)
        self.assertEqual(len(rebuilt.query_candidates(pool="opportunity")), 1)

    def test_archive_revision_mismatch_blocks_reconciliation_without_deletion(self):
        self._write_snapshot(_snapshot())
        archive_dir = self.root / "archives"
        build_snapshot_day_archive(self.root, archive_dir, "20260922")
        changed = _snapshot(priority=999.0)
        self._write_snapshot(changed)
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        self.snapshot_path.unlink()

        reconciliation = self.store.reconcile_source_directory(
            self.root,
            archive_directory=archive_dir,
        )

        self.assertFalse(reconciliation["synchronized"])
        self.assertEqual(reconciliation["blocking_archive_mismatch_count"], 1)
        self.assertEqual(reconciliation["deleted_manifest_count"], 0)
        self.assertEqual(self.store.status()["snapshot_count"], 1)
        self.assertEqual(
            self.store.query_candidates(pool="opportunity")[0]["priority_score"],
            999.0,
        )

    def test_invalid_manifest_makes_full_scope_incomplete(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        self.snapshot_path.write_text("{not-json", encoding="utf-8")
        self.store.index_snapshot_files([self.snapshot_path], force=True)

        status = self.store.status()
        self.assertEqual(status["build_scope"], "full")
        self.assertEqual(status["invalid_snapshot_count"], 1)
        self.assertFalse(status["index_complete"])

    def test_snapshot_discovery_excludes_auxiliary_json_files(self):
        self._write_snapshot(_snapshot())
        (self.root / "_history_index_20250429.json").write_text("{}", encoding="utf-8")
        (self.root / "README.json").write_text("{}", encoding="utf-8")

        paths = discover_scan_snapshot_files(self.root)

        self.assertEqual(paths, [self.snapshot_path])

    def test_auto_scan_planning_uses_complete_manifest_without_reading_json(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )

        with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", self.root):
            with patch(
                "stock_analyzer.scan_snapshot.beijing_now",
                return_value=datetime(2026, 9, 22, tzinfo=ZoneInfo("Asia/Shanghai")),
            ):
                with patch(
                    "stock_analyzer.scan_planner.scan_snapshot_files",
                    side_effect=AssertionError("JSON fallback should not run"),
                ):
                    plan = plan_scan_codes(
                        ["600001", "600002"],
                        "opportunity",
                        refresh_policy="auto",
                        start_date="2025-04-29",
                        index_store=self.store,
                    )

        self.assertEqual(plan["codes"], ["600002"])
        self.assertEqual(plan["summary"]["cache_hit_count"], 1)
        self.assertEqual(plan["summary"]["missing_count"], 1)

    def test_unknown_reason_is_rejected(self):
        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)

        with self.assertRaisesRegex(ValueError, "unknown candidate reason"):
            self.store.query_candidates(pool="opportunity", reason="not-a-reason")

    def test_opt_in_scan_index_api_returns_summary_page(self):
        import app as web_app

        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            client = web_app.app.test_client()
            response = client.get(
                "/api/scan_index/candidates"
                "?scan_type=opportunity&snapshot_day=2026-09-22"
                "&reason=plan_ready&limit=1&rank_mode=contextual"
            )
            invalid = client.get(
                "/api/scan_index/candidates?snapshot_day=not-a-date"
            )
            invalid_rank = client.get(
                "/api/scan_index/candidates?rank_mode=not-a-mode"
            )
        finally:
            web_app.scan_index_store = original_store

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["source"], "sqlite_index")
        self.assertTrue(payload["index_health"]["index_complete"])
        self.assertEqual(payload["latest_snapshot_day"], "2026-09-22")
        self.assertEqual(payload["history_snapshot_day"], "2026-09-22")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["code"], "600001")
        self.assertNotIn("facts", payload["results"][0])
        self.assertEqual(payload["ranking"]["requested_mode"], "contextual")
        self.assertEqual(payload["ranking"]["mode"], "snapshot_local")
        self.assertFalse(payload["ranking"]["context_applied"])
        self.assertTrue(payload["ranking"]["fallback_reason"])
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            invalid.get_json()["error"]["code"],
            "invalid_scan_index_query",
        )
        self.assertEqual(invalid_rank.status_code, 400)
        self.assertEqual(
            invalid_rank.get_json()["error"]["code"],
            "invalid_scan_index_query",
        )

    def test_contextual_historical_api_keeps_legacy_rows_outside_current_context(self):
        import app as web_app

        current = _snapshot()
        legacy = _snapshot(code="600002")
        legacy["strategy_version"] = "2026.09.09.2"
        legacy_path = self.root / "600002_20250429_20260922.json"
        self._write_snapshot(current)
        legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        self.store.index_snapshot_files([self.snapshot_path, legacy_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=2,
            source_directory=self.root,
        )
        self.store.materialize_rank_context(
            snapshot_day="20260922",
            strategy_version=SCAN_STRATEGY_VERSION,
            start_key="20250429",
            source_fingerprint=_rank_fingerprint("historical-context-v1"),
            candidates=[
                {
                    "pool": pool,
                    "code": "600001",
                    "event_date": "2026-09-22",
                    "context_priority_score": score,
                    "context_priority_group": "trade_ready",
                    "context_final_score": score / 10,
                }
                for pool, score in (("opportunity", 800), ("risk", 500))
            ],
        )
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            response = web_app.app.test_client().get(
                "/api/scan_index/candidates"
                "?scan_type=opportunity&snapshot_day=2026-09-22&rank_mode=CONTEXTUAL"
            )
        finally:
            web_app.scan_index_store = original_store

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 2)
        self.assertTrue(payload["ranking"]["context_applied"])
        self.assertEqual(payload["ranking"]["context_coverage"], "current_strategy_only")
        self.assertEqual([item["code"] for item in payload["results"]], ["600001", "600002"])
        self.assertIn("rank_context", payload["results"][0])
        self.assertNotIn("rank_context", payload["results"][1])

    def test_candidate_api_does_not_report_an_unbuilt_index_as_an_empty_pool(self):
        import app as web_app

        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            response = web_app.app.test_client().get(
                "/api/scan_index/candidates?scan_type=opportunity"
            )
        finally:
            web_app.scan_index_store = original_store

        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "scan_index_not_ready")
        self.assertEqual(payload["error"]["details"]["index_health"]["snapshot_count"], 0)

    def test_candidate_api_rejects_a_partial_index_explicitly(self):
        import app as web_app

        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path])
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            response = web_app.app.test_client().get(
                "/api/scan_index/candidates?scan_type=opportunity"
            )
        finally:
            web_app.scan_index_store = original_store

        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "scan_index_incomplete")
        self.assertEqual(payload["error"]["details"]["index_health"]["build_scope"], "partial")

    def test_latest_candidate_reads_exclude_stale_bars_but_exact_history_keeps_them(self):
        import app as web_app

        fresh = _snapshot(snapshot_day="20260923")
        fresh["data_date"] = "2026-09-23"
        stale = _snapshot(code="600002", snapshot_day="20260923")
        stale["data_date"] = "2026-09-21"
        stale["name"] = "样本B"
        for result in stale["results"].values():
            result["name"] = "样本B"
        stale_path = self.root / "600002_20250429_20260923.json"
        self.snapshot_path = self.root / "600001_20250429_20260923.json"
        self._write_snapshot(fresh)
        stale_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
        self.store.index_snapshot_files([self.snapshot_path, stale_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=2,
            source_directory=self.root,
        )
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            client = web_app.app.test_client()
            with (
                patch(
                    "stock_analyzer.scan_snapshot.beijing_now",
                    return_value=datetime(2026, 9, 23, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                ),
                patch(
                    "stock_analyzer.scan_snapshot.market_calendar_context",
                    return_value={"is_session": True},
                ),
            ):
                latest = client.get("/api/scan_index/candidates?scan_type=opportunity")
                latest_detail = client.get(
                    "/api/scan_index/candidates/600002?scan_type=opportunity"
                )
                history = client.get(
                    "/api/scan_index/candidates?scan_type=opportunity&snapshot_day=2026-09-23"
                )
                history_detail = client.get(
                    "/api/scan_index/candidates/600002"
                    "?scan_type=opportunity&snapshot_day=2026-09-23"
                )
        finally:
            web_app.scan_index_store = original_store

        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.get_json()["count"], 1)
        self.assertEqual(latest.get_json()["results"][0]["code"], "600001")
        self.assertEqual(latest_detail.status_code, 404)
        self.assertEqual(latest_detail.get_json()["error"]["code"], "candidate_not_found")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.get_json()["count"], 2)
        self.assertEqual(history_detail.status_code, 200)

    def test_candidate_api_reports_index_backend_errors_as_retryable(self):
        import app as web_app

        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            with (
                patch.object(self.store, "status", side_effect=RuntimeError("database offline")),
                self.assertLogs(web_app.app.logger, level="ERROR"),
            ):
                response = web_app.app.test_client().get(
                    "/api/scan_index/candidates?scan_type=opportunity"
                )
        finally:
            web_app.scan_index_store = original_store

        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "scan_index_unavailable")
        self.assertTrue(payload["error"]["retryable"])

    def test_json_candidate_read_remains_available_when_sqlite_is_unavailable(self):
        import app as web_app

        workspace = {
            "pools": {
                "opportunity": {
                    "count": 1,
                    "results": [{
                        "code": "600001",
                        "name": "样本A",
                        "event_date": "2026-09-22",
                    }],
                },
            },
            "latest_snapshot_day": "2026-09-22",
            "latest_data_date": "2026-09-22",
        }
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            with (
                patch.object(self.store, "status", side_effect=RuntimeError("database offline")),
                patch(
                    "stock_analyzer.web.scan_api.get_cached_scan_workspace",
                    return_value=workspace,
                ),
            ):
                response = web_app.app.test_client().get(
                    "/api/scan_workspace/candidates?scan_type=opportunity&compact=0"
                )
        finally:
            web_app.scan_index_store = original_store

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["code"], "600001")

    def test_default_compact_json_candidate_read_survives_sqlite_fingerprint_failure(self):
        import app as web_app

        self._write_snapshot(_snapshot())
        workspace = {
            "pools": {
                "opportunity": {
                    "count": 1,
                    "results": [{"code": "600001", "name": "样本A", "event_date": "2026-09-22"}],
                },
            },
            "latest_snapshot_day": "2026-09-22",
            "latest_data_date": "2026-09-22",
        }
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        cached_response = patch(
            "stock_analyzer.web.scan_api.get_cached_compact_workspace_response",
            return_value=workspace,
        )
        try:
            with (
                patch.object(
                    self.store,
                    "cache_fingerprint",
                    side_effect=RuntimeError("database offline"),
                ),
                patch(
                    "stock_analyzer.scan_workspace_persistent_cache.scan_snapshot.scan_snapshot_files",
                    return_value=[self.snapshot_path],
                ),
                cached_response as cached_response_mock,
            ):
                response = web_app.app.test_client().get(
                    "/api/scan_workspace?lite=1&active_type=opportunity"
                )
        finally:
            web_app.scan_index_store = original_store

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["pools"]["opportunity"]["results"][0]["code"],
            "600001",
        )
        fingerprint = cached_response_mock.call_args.args[1]
        self.assertEqual(fingerprint["snapshots"]["revision_source"], "filesystem")
        self.assertTrue(fingerprint["snapshots"]["file_revision"])

    def test_candidate_api_rejects_reason_filter_when_reason_tags_are_incomplete(self):
        import app as web_app

        self._write_snapshot(_snapshot())
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        health = self.store.status()
        health["reason_tags_complete"] = False
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            with patch.object(self.store, "status", return_value=health):
                response = web_app.app.test_client().get(
                    "/api/scan_index/candidates?reason=plan_ready"
                )
        finally:
            web_app.scan_index_store = original_store

        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "scan_index_incomplete")
        self.assertFalse(
            payload["error"]["details"]["index_health"]["reason_tags_complete"]
        )

    def test_historical_candidate_api_does_not_drop_legacy_strategy_rows(self):
        import app as web_app

        legacy = _snapshot()
        legacy["strategy_version"] = "2026.09.09.2"
        self._write_snapshot(legacy)
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            client = web_app.app.test_client()
            historical = client.get(
                "/api/scan_index/candidates"
                "?scan_type=opportunity&snapshot_day=2026-09-22&limit=1"
            )
            current = client.get("/api/scan_index/candidates?scan_type=opportunity&limit=1")
        finally:
            web_app.scan_index_store = original_store

        self.assertEqual(historical.status_code, 200)
        self.assertEqual(historical.get_json()["count"], 1)
        self.assertEqual(
            historical.get_json()["results"][0]["strategy_version"],
            "2026.09.09.2",
        )
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.get_json()["count"], 0)

    def test_scan_job_postprocess_indexes_latest_snapshot_for_codes(self):
        import app as web_app

        self._write_snapshot(_snapshot())
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            with (
                patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", self.root),
                patch(
                    "app.materialize_workspace_rank_context",
                    return_value={
                        "status": "materialized",
                        "candidate_count": 2,
                        "rank_context": {"available": True},
                    },
                ) as materialize,
            ):
                result = web_app.sync_scan_job_index(
                    {"started_at": "2026-09-22T10:00:00"},
                    ["600001", "000999"],
                )
        finally:
            web_app.scan_index_store = original_store

        self.assertEqual(result["status"], "indexed")
        self.assertEqual(result["snapshot_count"], 1)
        self.assertEqual(result["indexed"], 1)
        self.assertEqual(result["index"]["status"], "indexed")
        self.assertEqual(result["rank_context"]["status"], "materialized")
        self.assertEqual(materialize.call_count, 2)
        self.assertEqual(
            {call.kwargs["context_scope"] for call in materialize.call_args_list},
            {RANK_CONTEXT_SCOPE_SNAPSHOT, RANK_CONTEXT_SCOPE_LATEST_FRESH},
        )
        self.assertEqual(
            self.store.query_candidates(pool="opportunity")[0]["code"],
            "600001",
        )

    def test_scan_job_postprocess_degrades_when_rank_context_fails(self):
        import app as web_app

        self._write_snapshot(_snapshot())
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            with (
                patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", self.root),
                patch(
                    "app.materialize_workspace_rank_context",
                    side_effect=RuntimeError("rank unavailable"),
                ),
            ):
                result = web_app.sync_scan_job_index(
                    {"started_at": "2026-09-22T10:00:00"},
                    ["600001"],
                )
        finally:
            web_app.scan_index_store = original_store

        self.assertEqual(result["status"], "indexed_context_failed")
        self.assertEqual(result["indexed"], 1)
        self.assertEqual(result["rank_context"]["status"], "failed")
        self.assertEqual(result["rank_context"]["fallback"], "snapshot_local")

    def test_storage_reconciliation_failure_does_not_skip_rank_context(self):
        import app as web_app

        self._write_snapshot(_snapshot())
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            with (
                patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", self.root),
                patch.object(
                    self.store,
                    "reconcile_source_directory",
                    side_effect=SnapshotArchiveError("broken unrelated archive"),
                ),
                patch(
                    "app.materialize_workspace_rank_context",
                    return_value={
                        "status": "materialized",
                        "candidate_count": 2,
                        "rank_context": {"available": True},
                    },
                ) as materialize,
            ):
                result = web_app.sync_scan_job_index(
                    {"started_at": "2026-09-22T10:00:00"},
                    ["600001"],
                )
        finally:
            web_app.scan_index_store = original_store

        self.assertEqual(result["status"], "indexed")
        self.assertEqual(result["index"]["reconciliation"]["status"], "failed")
        self.assertEqual(materialize.call_count, 2)

    def test_candidate_detail_api_projects_snapshot_and_detects_revision_changes(self):
        import app as web_app

        payload = _snapshot()
        opportunity = payload["results"]["opportunity"]
        opportunity["explanation"] = {
            "headline": "突破候选",
            "summary": "结构与计划门一致。",
            "drivers": [{"label": "结构", "detail": "箱体突破"}],
        }
        opportunity["trade_plan"] = {
            "status": "ready",
            "entry": {"price": 10.6},
            "stop": {"price": 9.8},
        }
        opportunity["v2_state_model"] = {
            "event_mapping": {"signal_key": "v2_breakout"},
            "scores": {"confirm": 5},
            "next_action": "等待价格确认",
            "v2_permission_model": {
                "permission": "breakout_allowed",
                "can_open": True,
            },
            "facts": {
                "setup": {"breakout_setup": True},
                "structure": {
                    "summary": "箱体结构",
                    "candidate": {"available": True},
                    "normalized_bars": [{"close": 10.5}] * 100,
                    "rectangle_candidates": [{"upper": 10.5}] * 20,
                },
                "trigger": {"breaks_prev_high": True},
                "risk": {"has_risk": False},
                "exit_gate": {"action": "hold"},
                "macro_tide": {"permission": "allowed"},
                "target_structure": {"selected_breakout_target": {"price": 12.0}},
            },
        }
        self._write_snapshot(payload)
        self.store.index_snapshot_files([self.snapshot_path], reset=True)
        self.store.record_build_scope(
            "full",
            source_snapshot_count=1,
            source_directory=self.root,
        )
        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            client = web_app.app.test_client()
            response = client.get(
                "/api/scan_index/candidates/600001"
                "?scan_type=opportunity&snapshot_day=2026-09-22"
            )
            payload["name"] = "已被外部改写"
            self._write_snapshot(payload)
            conflict = client.get(
                "/api/scan_index/candidates/600001"
                "?scan_type=opportunity&snapshot_day=2026-09-22"
            )
        finally:
            web_app.scan_index_store = original_store

        detail = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(detail["schema_version"], 2)
        self.assertEqual(detail["summary"]["code"], "600001")
        self.assertNotIn("snapshot_path", detail["summary"])
        self.assertEqual(detail["decision_state"]["next_action"], "等待价格确认")
        self.assertEqual(detail["rule_results"]["scores"]["confirm"], 5)
        self.assertEqual(detail["decision_explanation"]["headline"], "突破候选")
        self.assertNotIn("normalized_bars", detail["structure_facts"]["structure"])
        self.assertNotIn("rectangle_candidates", detail["structure_facts"]["structure"])
        self.assertEqual(detail["permission"]["permission"], "breakout_allowed")
        self.assertEqual(detail["conditional_plan"]["status"], "ready")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(
            conflict.get_json()["error"]["code"],
            "snapshot_revision_mismatch",
        )

    def test_candidate_detail_does_not_misreport_an_unindexed_code_as_not_found(self):
        import app as web_app

        original_store = web_app.scan_index_store
        web_app.scan_index_store = self.store
        try:
            response = web_app.app.test_client().get(
                "/api/scan_index/candidates/600001?scan_type=opportunity"
            )
        finally:
            web_app.scan_index_store = original_store

        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "scan_index_not_ready")


if __name__ == "__main__":
    unittest.main()
