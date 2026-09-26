import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import app
from tests.fixtures import apply_legacy_entry, build_minimal_signal_frame
from stock_analyzer.scan_planner import plan_scan_codes
from stock_analyzer.scan_snapshot import build_scan_snapshot, write_scan_snapshot
from stock_analyzer.scan_workspace import collect_scan_workspace
from stock_analyzer.versioning import (
    DATA_ADJUST,
    SCAN_STRATEGY_VERSION,
    SCAN_SNAPSHOT_SCHEMA_VERSION,
)


class ScanWorkspaceTest(unittest.TestCase):
    def _minimal_signal_frame(self, rows=10):
        return build_minimal_signal_frame(rows=rows)

    def test_plan_scan_codes_filters_cached_codes_for_auto_policy(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=1, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    plan = plan_scan_codes(
                        ["600063", "000001", "bad"],
                        "opportunity",
                        refresh_policy="auto",
                        start_date="2025-04-29",
                    )

        self.assertEqual(plan["codes"], ["000001"])
        self.assertEqual(plan["summary"]["requested_count"], 3)
        self.assertEqual(plan["summary"]["eligible_count"], 2)
        self.assertEqual(plan["summary"]["queued_count"], 1)
        self.assertEqual(plan["summary"]["skipped_count"], 1)
        self.assertEqual(plan["summary"]["cache_hit_count"], 1)
        self.assertEqual(plan["summary"]["missing_count"], 1)
        self.assertEqual(plan["summary"]["invalid_count"], 1)

    def test_plan_scan_codes_requeues_previous_data_after_trading_close(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11 16:00:00")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    plan = plan_scan_codes(
                        ["600063"],
                        "opportunity",
                        refresh_policy="auto",
                        start_date="2025-04-29",
                    )

        self.assertEqual(plan["codes"], ["600063"])
        self.assertEqual(plan["summary"]["queued_count"], 1)
        self.assertEqual(plan["summary"]["stale_count"], 1)
        self.assertEqual(plan["summary"]["cache_hit_count"], 0)

    def test_plan_scan_codes_auto_requeues_legacy_strategy_snapshot(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    snapshot.pop("strategy_version", None)
                    snapshot.pop("strategy_meta", None)
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    auto_plan = plan_scan_codes(
                        ["600063"],
                        "opportunity",
                        refresh_policy="auto",
                        start_date="2025-04-29",
                    )
                    cache_plan = plan_scan_codes(
                        ["600063"],
                        "opportunity",
                        refresh_policy="cache",
                        start_date="2025-04-29",
                    )

        self.assertEqual(auto_plan["codes"], ["600063"])
        self.assertEqual(auto_plan["summary"]["queued_count"], 1)
        self.assertEqual(auto_plan["summary"]["legacy_strategy_count"], 1)
        self.assertEqual(auto_plan["summary"]["cache_hit_count"], 0)
        self.assertEqual(cache_plan["codes"], [])
        self.assertEqual(cache_plan["summary"]["cache_hit_count"], 1)

    def test_plan_scan_codes_respects_cache_and_force_policy_boundaries(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=1, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    cache_plan = plan_scan_codes(
                        ["600063", "000001"],
                        "opportunity",
                        refresh_policy="cache",
                        start_date="2025-04-29",
                    )
                    force_plan = plan_scan_codes(
                        ["600063", "000001"],
                        "opportunity",
                        refresh_policy="force",
                        start_date="2025-04-29",
                    )

        self.assertEqual(cache_plan["codes"], [])
        self.assertEqual(cache_plan["summary"]["queued_count"], 0)
        self.assertEqual(cache_plan["summary"]["skipped_count"], 2)
        self.assertEqual(cache_plan["summary"]["cache_hit_count"], 1)
        self.assertEqual(cache_plan["summary"]["missing_count"], 1)
        self.assertEqual(force_plan["codes"], ["600063", "000001"])
        self.assertEqual(force_plan["summary"]["queued_count"], 2)
        self.assertEqual(force_plan["summary"]["skipped_count"], 0)

    def test_collect_scan_workspace_reads_local_snapshots_by_pool(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir) / "catalog"):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        older_snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-09", sector="半导体")
                        write_scan_snapshot(older_snapshot, start_date="2025-04-29", snapshot_day="2026-05-09")
                        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10", sector="半导体")
                        write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        workspace = collect_scan_workspace(start_date="2025-04-29")

        self.assertEqual(workspace["scanned_count"], 1)
        self.assertEqual(workspace["valid_snapshot_count"], 2)
        self.assertEqual(workspace["snapshot_meta"]["schema_version"], SCAN_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(workspace["snapshot_meta"]["strategy_version"], SCAN_STRATEGY_VERSION)
        self.assertEqual(workspace["snapshot_meta"]["current_strategy_snapshot_count"], 1)
        self.assertEqual(workspace["snapshot_meta"]["legacy_snapshot_count"], 0)
        self.assertEqual(workspace["snapshot_meta"]["stored_current_strategy_snapshot_count"], 2)
        self.assertEqual(workspace["snapshot_meta"]["stored_legacy_snapshot_count"], 0)
        self.assertEqual(workspace["strategy_meta"]["strategy_version"], SCAN_STRATEGY_VERSION)
        self.assertEqual(workspace["snapshot_meta"]["health"], "healthy")
        self.assertEqual(workspace["strategy_health"]["health"], "warming")
        self.assertEqual(workspace["strategy_health"]["current_strategy_result_count"], 1)
        self.assertEqual(workspace["strategy_health"]["legacy_strategy_result_count"], 0)
        self.assertEqual(workspace["snapshot_meta"]["scanned_count"], 1)
        self.assertEqual(workspace["snapshot_meta"]["latest_snapshot_day"], "2026-05-10")
        self.assertEqual(workspace["pools"]["opportunity"]["count"], 1)
        self.assertEqual(workspace["pools"]["opportunity"]["current_strategy_count"], 1)
        result = workspace["pools"]["opportunity"]["results"][0]
        self.assertEqual(result["name"], "示例股票")
        self.assertEqual(result["sector"], "半导体")
        self.assertEqual(result["strategy_status"], "current")
        self.assertEqual(result["strategy_source_label"], "当前策略")
        self.assertNotIn("sector_score", result)
        self.assertEqual(result["scan_admission_source"], "v2_state")
        self.assertEqual(result["snapshot_day"], "2026-05-10")
        self.assertIn("explanation", result)
        self.assertIn("card_summary", result["explanation"])
        self.assertIn("view_model", result)
        self.assertIn("trade_plan", result)
        self.assertNotIn("mainline_context", workspace)
        self.assertNotIn("market_decision", workspace)
        self.assertNotIn("theme_lines", workspace)
        self.assertEqual(workspace["pools"]["bottom_div"]["count"], 0)
        self.assertEqual(workspace["sector_overview"][0]["sector"], "半导体")
        self.assertEqual(workspace["sector_overview"][0]["opportunity_count"], 1)
        self.assertEqual(workspace["sector_overview"][0]["bottom_div_count"], 0)

    def test_collect_scan_workspace_sorts_system_results_by_v2_priority(self):
        breakout_snapshot = {
            "version": SCAN_SNAPSHOT_SCHEMA_VERSION,
            "strategy_version": SCAN_STRATEGY_VERSION,
            "data_adjust": DATA_ADJUST,
            "code": "600063",
            "name": "突破股票",
            "sector": "半导体",
            "concepts": [],
            "snapshot_day": "20260510",
            "data_date": "2026-05-10",
            "computed_scan_types": ["opportunity"],
            "results": {
                "opportunity": {
                    "code": "600063",
                    "name": "突破股票",
                    "scan_type": "opportunity",
                    "date": "2026-05-10",
                    "event_date": "2026-05-10",
                    "signal_key": "composite_breakout",
                    "signal": "C突",
                    "signal_label": "C突",
                    "signal_name": "综合突破",
                    "reason": "前高突破",
                    "setup_score": 1,
                    "confirm_score": 4,
                    "risk_score": 0,
                    "rank_score": 45.0,
                    "v2_plan_status": "ready",
                    "v2_state_model": {
                        "state": "entry_breakout",
                        "state_label": "突破可交易",
                        "permission": "breakout_allowed",
                        "permission_label": "允许突破计划",
                        "signal": "C突",
                        "signal_name": "突破入场",
                        "role": "entry",
                        "role_label": "可交易",
                        "tone": "positive",
                        "requires_trade_plan": True,
                        "requires_stop_loss": True,
                        "facts": {
                            "macro_tide": {
                                "available": True,
                                "summary": "个股宏观条件通过",
                                "ma250": {"available": True, "above": True},
                                "weekly_macd": {"available": True},
                            },
                        },
                        "v2_permission_model": {
                            "plan_status": "ready",
                            "plan_status_label": "计划可校验",
                        },
                    },
                },
            },
        }
        repair_snapshot = {
            "version": SCAN_SNAPSHOT_SCHEMA_VERSION,
            "strategy_version": SCAN_STRATEGY_VERSION,
            "data_adjust": DATA_ADJUST,
            "code": "000001",
            "name": "修复股票",
            "sector": "半导体",
            "concepts": [],
            "snapshot_day": "20260510",
            "data_date": "2026-05-10",
            "computed_scan_types": ["opportunity"],
            "results": {
                "opportunity": {
                    "code": "000001",
                    "name": "修复股票",
                    "scan_type": "opportunity",
                    "date": "2026-05-10",
                    "event_date": "2026-05-10",
                    "signal_key": "composite_confirm",
                    "signal": "C观",
                    "signal_label": "C观",
                    "signal_name": "修复确认",
                    "reason": "底背离修复",
                    "setup_score": 2,
                    "confirm_score": 3,
                    "risk_score": 0,
                    "rank_score": 55.0,
                },
            },
        }

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir) / "catalog"):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        write_scan_snapshot(breakout_snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        write_scan_snapshot(repair_snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        workspace = collect_scan_workspace(
                            start_date="2025-04-29",
                        )

        results = workspace["pools"]["opportunity"]["results"]
        self.assertEqual([item["code"] for item in results], ["600063", "000001"])
        self.assertEqual(results[0]["v2_priority_group"], "trade_ready")
        self.assertEqual(results[0]["v2_environment_permission"], "allowed")
        self.assertEqual(results[1]["v2_priority_group"], "repair_watch")
        self.assertGreater(results[0]["v2_priority_score"], results[1]["v2_priority_score"])

    def test_collect_scan_workspace_caps_loaded_results_and_reports_total(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir) / "catalog"):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        for code in ["600001", "600002", "600003"]:
                            snapshot = build_scan_snapshot(code, "示例股票" + code[-1], frame, snapshot_day="2026-05-10")
                            write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        workspace = collect_scan_workspace(start_date="2025-04-29", max_items=2)

        pool = workspace["pools"]["opportunity"]
        self.assertEqual(workspace["max_items"], 2)
        self.assertEqual(pool["count"], 3)
        self.assertEqual(pool["loaded_count"], 2)
        self.assertTrue(pool["has_more"])
        self.assertEqual(len(pool["results"]), 2)

    def test_collect_scan_workspace_builds_concept_overview_from_cached_profiles(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")

        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir) / "catalog"
            cache_dir.mkdir(parents=True)
            (cache_dir / "stock_concepts.json").write_text(
                json.dumps({
                    "source": "test",
                    "stocks": {"600063": ["存储芯片", "国企改革"]},
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir) / "snapshots"):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", cache_dir):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10", sector="半导体")
                        write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        workspace = collect_scan_workspace(
                            start_date="2025-04-29",
                        )

        opportunity = workspace["pools"]["opportunity"]
        result = opportunity["results"][0]
        self.assertEqual(result["concepts"], ["存储芯片", "国企改革"])
        self.assertNotIn("concept_score", result)
        self.assertNotIn("concept_market_trend", result)
        self.assertNotIn("market_boost", result)
        self.assertEqual(opportunity["concept_coverage"]["covered_count"], 1)
        self.assertEqual(opportunity["concept_coverage"]["coverage_rate"], 100.0)
        self.assertEqual(workspace["concept_overview"][0]["concept"], "存储芯片")
        self.assertEqual(workspace["concept_overview"][0]["opportunity_count"], 1)
        self.assertEqual(workspace["concept_overview"][0]["bottom_div_count"], 0)
        self.assertNotIn("structure_score", workspace["concept_overview"][0])
        self.assertEqual(workspace["market_structure_meta"]["mode"], "candidate_distribution")
        self.assertNotIn("theme_lines", workspace)

    def test_collect_scan_workspace_keeps_profile_relations_descriptive_only(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cache_dir = tmp_path / "catalog"
            cache_dir.mkdir(parents=True)
            (cache_dir / "stock_profiles.json").write_text(json.dumps({
                "600063": {"code": "600063", "name": "示例股票", "sector": "电力设备", "concepts": ["储能"]},
                "000001": {"code": "000001", "name": "样本股票", "sector": "电力设备", "concepts": ["储能"]},
            }, ensure_ascii=False), encoding="utf-8")
            (cache_dir / "stock_relation_evidence.json").write_text(json.dumps({
                "stocks": {
                    "600063": [{
                        "relation_name": "储能",
                        "relation_kind": "business",
                        "relation_type": "core_business",
                        "source": "manual",
                        "confidence": 0.93,
                    }],
                    "000001": [{
                        "relation_name": "储能",
                        "relation_kind": "concept",
                        "relation_type": "weak_association",
                        "source": "manual",
                        "confidence": 0.42,
                    }],
                }
            }, ensure_ascii=False), encoding="utf-8")
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", tmp_path / "snapshots"):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", cache_dir):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                        write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        workspace = collect_scan_workspace(
                            start_date="2025-04-29",
                        )

        concept = next(item for item in workspace["concept_overview"] if item.get("concept") == "储能")
        result = workspace["pools"]["opportunity"]["results"][0]

        self.assertEqual(concept["concept"], "储能")
        self.assertEqual(concept["count"], 1)
        self.assertIn("储能", result["profile_relation_summary"])
        self.assertNotIn("relation_quality_score", concept)
        self.assertNotIn("market_lines", workspace)
        self.assertEqual(workspace["market_structure_meta"]["mode"], "candidate_distribution")

    def test_build_scan_snapshot_records_strategy_version(self):
        frame = self._minimal_signal_frame(rows=12)
        apply_legacy_entry(frame)

        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")

        self.assertEqual(snapshot["version"], SCAN_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(snapshot["strategy_version"], SCAN_STRATEGY_VERSION)
        self.assertEqual(snapshot["strategy_meta"]["strategy_version"], SCAN_STRATEGY_VERSION)
        self.assertEqual(snapshot["strategy_meta"]["snapshot_schema_version"], SCAN_SNAPSHOT_SCHEMA_VERSION)

    def test_collect_scan_workspace_marks_legacy_strategy_snapshots(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    snapshot.pop("strategy_version", None)
                    snapshot.pop("strategy_meta", None)
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    workspace = collect_scan_workspace(start_date="2025-04-29")

        self.assertEqual(workspace["valid_snapshot_count"], 1)
        self.assertEqual(workspace["current_strategy_snapshot_count"], 0)
        self.assertEqual(workspace["legacy_snapshot_count"], 1)
        self.assertEqual(workspace["snapshot_meta"]["health"], "legacy")
        self.assertEqual(workspace["snapshot_meta"]["health_label"], "策略待刷新")
        self.assertEqual(workspace["snapshot_meta"]["health_summary"], "旧策略待重算")
        self.assertIn("旧版 1", workspace["snapshot_meta"]["health_detail"])
        self.assertEqual(workspace["strategy_health"]["health"], "migration")
        self.assertEqual(workspace["strategy_health"]["legacy_strategy_result_count"], 1)
        self.assertEqual(workspace["strategy_health"]["current_strategy_result_count"], 0)
        self.assertEqual(workspace["pools"]["opportunity"]["current_strategy_count"], 0)
        self.assertEqual(workspace["pools"]["opportunity"]["legacy_strategy_count"], 1)
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["strategy_status"], "legacy")
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["strategy_source_label"], "旧策略")

    def test_history_workspace_reports_snapshot_strategy_version(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-30")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-29")
                    snapshot["strategy_version"] = "2026.05.27.1"
                    snapshot["strategy_meta"]["strategy_version"] = "2026.05.27.1"
                    snapshot["strategy_meta"]["strategy_label"] = "旧版综合策略"
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-29")
                    workspace = collect_scan_workspace(
                        start_date="2025-04-29",
                        snapshot_day="2026-05-29",
                    )

        self.assertTrue(workspace["history_mode"])
        self.assertEqual(workspace["snapshot_meta"]["health"], "history")
        self.assertEqual(workspace["snapshot_meta"]["strategy_version"], "2026.05.27.1")
        self.assertEqual(workspace["snapshot_meta"]["strategy_label"], "旧版综合策略")
        self.assertEqual(workspace["snapshot_meta"]["current_code_strategy_version"], SCAN_STRATEGY_VERSION)
        self.assertEqual(workspace["snapshot_meta"]["strategy_versions"], [{
            "version": "2026.05.27.1",
            "label": "旧版综合策略",
            "count": 1,
            "status": "legacy",
        }])
        self.assertIn("旧版综合策略 2026.05.27.1", workspace["snapshot_meta"]["health_detail"])

    def test_collect_scan_workspace_ignores_replaced_legacy_snapshot_for_health(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    legacy = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-09")
                    legacy.pop("strategy_version", None)
                    legacy.pop("strategy_meta", None)
                    write_scan_snapshot(legacy, start_date="2025-04-29", snapshot_day="2026-05-09")

                    current = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(current, start_date="2025-04-29", snapshot_day="2026-05-10")
                    workspace = collect_scan_workspace(start_date="2025-04-29")

        self.assertEqual(workspace["valid_snapshot_count"], 2)
        self.assertEqual(workspace["current_strategy_snapshot_count"], 1)
        self.assertEqual(workspace["legacy_snapshot_count"], 0)
        self.assertEqual(workspace["stored_current_strategy_snapshot_count"], 1)
        self.assertEqual(workspace["stored_legacy_snapshot_count"], 1)
        self.assertEqual(workspace["snapshot_meta"]["health"], "healthy")
        self.assertEqual(workspace["snapshot_meta"]["stored_legacy_snapshot_count"], 1)
        self.assertEqual(workspace["strategy_health"]["legacy_strategy_result_count"], 0)
        self.assertEqual(workspace["pools"]["opportunity"]["legacy_strategy_count"], 0)
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["strategy_status"], "current")

    def test_collect_scan_workspace_enriches_name_and_sector_from_profile_cache(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            profile_dir = tmp_path / "catalog"
            profile_dir.mkdir()
            (profile_dir / "stock_profiles.json").write_text(
                json.dumps({
                    "600063": {"code": "600063", "name": "示例股票", "sector": "半导体", "concepts": ["AI芯片"]},
                    "000001": {"code": "000001", "name": "样本成员", "sector": "半导体", "concepts": ["AI芯片"]},
                }),
                encoding="utf-8",
            )
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", tmp_path / "snapshots"):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", profile_dir):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        snapshot = build_scan_snapshot("600063", "600063", frame, snapshot_day="2026-05-10")
                        write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        workspace = collect_scan_workspace(start_date="2025-04-29")

        result = workspace["pools"]["opportunity"]["results"][0]
        self.assertEqual(result["name"], "示例股票")
        self.assertEqual(result["sector"], "半导体")
        self.assertEqual(result["concepts"], ["AI芯片"])
        self.assertEqual(workspace["sector_overview"][0]["count"], 1)
        self.assertEqual(workspace["concept_overview"][0]["count"], 1)
        self.assertNotIn("market_member_count", workspace["sector_overview"][0])
        self.assertNotIn("width_label", workspace["concept_overview"][0])
        self.assertEqual(workspace["market_structure_meta"]["mode"], "candidate_distribution")
        self.assertEqual(workspace["market_structure_meta"]["mode_label"], "候选分布统计")
        self.assertIn("score_confidence", result)
        self.assertEqual(result["score_confidence_label"], "待验证")

    def test_collect_scan_workspace_reports_expired_snapshot_health(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-20")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    workspace = collect_scan_workspace(start_date="2025-04-29")

        self.assertEqual(workspace["scanned_count"], 0)
        self.assertEqual(workspace["valid_snapshot_count"], 0)
        self.assertEqual(workspace["stale_snapshot_count"], 1)
        self.assertEqual(workspace["snapshot_meta"]["health"], "expired")
        self.assertEqual(workspace["snapshot_meta"]["health_label"], "已过期")
        self.assertEqual(workspace["snapshot_meta"]["health_summary"], "快照已过期")
        self.assertIn("建议重建", workspace["snapshot_meta"]["health_detail"])
        self.assertEqual(workspace["snapshot_meta"]["action_label"], "重建")

    def test_collect_scan_workspace_keeps_sector_distribution_without_scoring(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=1, watch=False)
        frame.loc[11, "composite_risk_warn"] = True
        frame.loc[11, "composite_risk_reason"] = "顶背离 / MACD转弱"

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir) / "catalog"):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        first = build_scan_snapshot("600063", "示例股票A", frame, snapshot_day="2026-05-10", sector="半导体")
                        second = build_scan_snapshot("000001", "示例股票B", frame, snapshot_day="2026-05-10", sector="半导体")
                        write_scan_snapshot(first, start_date="2025-04-29", snapshot_day="2026-05-10")
                        write_scan_snapshot(second, start_date="2025-04-29", snapshot_day="2026-05-10")
                        workspace = collect_scan_workspace(start_date="2025-04-29")

        overview = workspace["sector_overview"][0]
        opportunity = workspace["pools"]["opportunity"]["results"][0]
        self.assertEqual(overview["sector"], "半导体")
        self.assertEqual(overview["opportunity_count"], 2)
        self.assertEqual(overview["risk_count"], 0)
        self.assertNotIn("sector_score", opportunity)
        self.assertNotIn("sector_opportunity_count", opportunity)
        self.assertIn("final_score", opportunity)
        calibration = workspace["resonance_calibration"]
        self.assertEqual(calibration["method"], "disabled")
        self.assertEqual(calibration["buckets"], [])
        self.assertNotIn("bucket", opportunity["score_confidence"])

    def test_collect_scan_workspace_does_not_expose_board_market_context(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            catalog_dir = Path(tmp_dir) / "catalog"
            catalog_dir.mkdir(parents=True)
            profiles = {
                f"000{i:03d}": {"code": f"000{i:03d}", "name": f"样本{i}", "sector": f"A{i:02d}"}
                for i in range(30)
            }
            profiles["600063"] = {"code": "600063", "name": "示例股票", "sector": "半导体"}
            (catalog_dir / "stock_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", catalog_dir):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10", sector="半导体")
                        write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        workspace = collect_scan_workspace(
                            start_date="2025-04-29",
                        )

        overview = next(item for item in workspace["sector_overview"] if item.get("sector") == "半导体")
        result = workspace["pools"]["opportunity"]["results"][0]
        self.assertEqual(overview["sector"], "半导体")
        self.assertEqual(overview["opportunity_count"], 1)
        self.assertEqual(workspace["market_structure_meta"]["sectors"]["market_supported_count"], 0)
        self.assertNotIn("sector_market_trend", result)
        self.assertNotIn("sector_market_context_status", result)
        self.assertNotIn("market_boost", result)
        self.assertEqual(result["final_score"], result["rank_score"])
        self.assertNotIn("共振", result["explanation"]["summary"])
        self.assertNotIn("共振", [badge["label"] for badge in result["explanation"]["score_badges"]])

    def test_collect_scan_workspace_replays_forward_returns_from_history_cache(self):
        dates = pd.bdate_range("2026-01-02", periods=8)
        history = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "open": [10, 11, 12, 13, 14, 15, 16, 17],
            "close": [10, 11, 12, 13, 14, 15, 16, 17],
            "high": [10, 11, 12, 13, 14, 15, 16, 17],
            "low": [10, 11, 12, 13, 14, 15, 16, 17],
            "amount": [1000] * 8,
        })
        snapshot = {
            "version": 1,
            "code": "600063",
            "name": "示例股票",
            "sector": "半导体",
            "snapshot_day": "20260102",
            "data_date": "2026-01-02",
            "rows": 1,
            "computed_scan_types": ["opportunity"],
            "results": {
                "opportunity": {
                    "code": "600063",
                    "name": "示例股票",
                    "sector": "半导体",
                    "event_date": "2026-01-02",
                    "date": "2026-01-02",
                    "rank_score": 50.0,
                    "win_rate": 60.0,
                    "avg_ret": 2.0,
                    "scan_type": "opportunity",
                    "v2_state_model": {"permission": "pullback_allowed", "state": "entry_pullback"},
                },
            },
        }

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            history_dir = tmp_path / "history"
            history_dir.mkdir()
            history.to_csv(history_dir / "600063_20250429_20260115_qfq.csv", index=False)
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", tmp_path / "snapshots"):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", tmp_path / "catalog"):
                    with patch("stock_analyzer.data_fetcher.CACHE_DIR", history_dir):
                        with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-01-07")):
                            write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-01-02")
                            workspace = collect_scan_workspace(start_date="2025-04-29", snapshot_day="2026-01-02")
                            next_open_workspace = collect_scan_workspace(
                                start_date="2025-04-29",
                                snapshot_day="2026-01-02",
                                replay_entry_model="next_open",
                            )

        replay = workspace["replay_calibration"]
        next_open_replay = next_open_workspace["replay_calibration"]
        result = workspace["pools"]["opportunity"]["results"][0]
        self.assertEqual(replay["method"], "disabled")
        self.assertEqual(replay["entry_model"], "event_close")
        self.assertEqual(replay["buckets"], [])
        self.assertEqual(next_open_replay["entry_model"], "next_open")
        self.assertEqual(next_open_replay["method"], "disabled")
        self.assertEqual(next_open_replay["buckets"], [])
        self.assertNotIn("replay_5d_sample_count", result["score_confidence"])
        self.assertNotIn("replay_5d_avg_ret", result["score_confidence"])
        self.assertNotIn("胜率 100.0%", result["score_confidence"]["basis"])

    def test_scan_workspace_api_returns_cached_pool_summary(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    response = app.app.test_client().get("/api/scan_workspace")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["scanned_count"], 1)
        self.assertEqual(payload["pools"]["opportunity"]["count"], 1)
        self.assertIn("resonance_calibration", payload)
        self.assertEqual(payload["resonance_calibration"]["method"], "disabled")
        self.assertEqual(payload["resonance_calibration"]["buckets"], [])
        self.assertIn("replay_calibration", payload)
        self.assertEqual(payload["replay_calibration"]["horizons"], [3, 5, 10])
        self.assertEqual(payload["snapshot_meta"]["health"], "healthy")
        self.assertEqual(payload["snapshot_meta"]["latest_snapshot_day"], "2026-05-10")

    def test_scan_workspace_api_keeps_retired_replay_calibration_disabled(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    client = app.app.test_client()
                    lite_response = client.get("/api/scan_workspace?lite=1&include_replay=1")
                    full_response = client.get("/api/scan_workspace?snapshot_day=2026-05-10")

        lite_payload = lite_response.get_json()
        full_payload = full_response.get_json()
        self.assertEqual(lite_response.status_code, 200)
        self.assertEqual(full_response.status_code, 200)
        self.assertEqual(lite_payload["replay_calibration"]["method"], "disabled")
        self.assertEqual(lite_payload["replay_calibration"]["entry_model"], "event_close")
        self.assertEqual(lite_payload["replay_calibration"]["horizons"], [3, 5, 10])
        self.assertEqual(lite_payload["market_structure_meta"]["mode"], "candidate_distribution")
        self.assertEqual(full_payload["replay_calibration"]["method"], "disabled")

    def test_scan_workspace_api_honors_result_limit(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        apply_legacy_entry(frame, setup=2, confirm=3, risk=0, watch=False)

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", Path(tmp_dir) / "catalog"):
                    with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                        for code in ["600001", "600002", "600003"]:
                            snapshot = build_scan_snapshot(code, "示例股票" + code[-1], frame, snapshot_day="2026-05-10")
                            write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                        response = app.app.test_client().get("/api/scan_workspace?limit=2")

        payload = response.get_json()
        pool = payload["pools"]["opportunity"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["max_items"], 2)
        self.assertEqual(pool["count"], 3)
        self.assertEqual(pool["loaded_count"], 2)
        self.assertTrue(pool["has_more"])
        self.assertEqual(len(pool["results"]), 2)
