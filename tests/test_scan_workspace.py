import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import app
from stock_analyzer.scan_planner import plan_scan_codes
from stock_analyzer.scan_snapshot import build_scan_snapshot, write_scan_snapshot
from stock_analyzer.scan_workspace import collect_scan_workspace
from stock_analyzer.versioning import (
    SCAN_STRATEGY_VERSION,
    SCAN_SNAPSHOT_SCHEMA_VERSION,
)


class ScanWorkspaceTest(unittest.TestCase):
    def _minimal_signal_frame(self, rows=10):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=rows, freq="D"),
            "open": [10.0] * rows,
            "high": [10.5] * rows,
            "low": [9.8] * rows,
            "close": [10.0 + i * 0.1 for i in range(rows)],
            "custom": [0.0] * rows,
            "dif": [0.0] * rows,
            "dea": [0.0] * rows,
            "macd_hist": [0.0] * rows,
            "ma20": [10.0] * rows,
            "vwap": [10.0] * rows,
        })
        for column in [
            "is_b_point",
            "is_pullback_b",
            "is_s_point",
            "touch_upper",
            "break_ma5",
            "is_bottom_divergence",
            "is_top_divergence",
            "new_is_b_point",
            "new_is_pullback_b",
            "new_is_s_point",
            "opt_is_b_point",
            "opt_is_pullback_b",
            "opt_is_s_warn",
            "opt_is_s_confirm",
            "opt_is_s_point",
            "composite_entry",
            "composite_risk_warn",
            "composite_exit",
            "composite_risk",
        ]:
            frame[column] = False
        frame["composite_entry_type"] = ""
        frame["composite_risk_type"] = ""
        frame["composite_exit_type"] = ""
        frame["composite_entry_reason"] = ""
        frame["composite_risk_reason"] = ""
        return frame

    def test_plan_scan_codes_filters_cached_codes_for_auto_policy(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        frame["composite_setup_score"] = [1] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"
        frame.loc[10, "is_bottom_divergence"] = True

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
        self.assertEqual(workspace["snapshot_meta"]["health_summary"], "快照可用")
        self.assertIn("策略", workspace["snapshot_meta"]["health_detail"])
        self.assertEqual(workspace["strategy_health"]["health"], "warming")
        self.assertEqual(workspace["strategy_health"]["current_strategy_result_count"], 2)
        self.assertEqual(workspace["strategy_health"]["legacy_strategy_result_count"], 0)
        self.assertEqual(workspace["snapshot_meta"]["scanned_count"], 1)
        self.assertEqual(workspace["snapshot_meta"]["latest_snapshot_day"], "2026-05-10")
        self.assertEqual(workspace["pools"]["opportunity"]["count"], 1)
        self.assertEqual(workspace["pools"]["opportunity"]["current_strategy_count"], 1)
        self.assertEqual(workspace["pools"]["opportunity"]["legacy_strategy_count"], 0)
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["name"], "示例股票")
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["sector"], "半导体")
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["strategy_status"], "current")
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["strategy_source_label"], "当前策略")
        self.assertGreater(workspace["pools"]["opportunity"]["results"][0]["sector_score"], 0)
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["sector_signal_count"], 2)
        self.assertEqual(workspace["pools"]["opportunity"]["concept_coverage"]["coverage_rate"], 0.0)
        self.assertIn("sector_width_label", workspace["pools"]["opportunity"]["results"][0])
        self.assertIn("opportunity_density", workspace["sector_overview"][0])
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["snapshot_day"], "2026-05-10")
        explanation = workspace["pools"]["opportunity"]["results"][0]["explanation"]
        self.assertEqual(explanation["version"], 1)
        self.assertIn("板块", explanation["summary"])
        self.assertIn("card_summary", explanation)
        self.assertIn("view_model", workspace["pools"]["opportunity"]["results"][0])
        self.assertIn("card_summary", workspace["pools"]["opportunity"]["results"][0]["view_model"])
        self.assertIn("trade_plan", workspace["pools"]["opportunity"]["results"][0])
        self.assertNotIn("mainline_context", workspace["pools"]["opportunity"]["results"][0])
        self.assertNotIn("mainline_context", workspace["pools"]["opportunity"]["results"][0]["trade_plan"])
        self.assertEqual(workspace["pools"]["opportunity"]["results"][0]["trade_plan"]["status"], "blocked")
        self.assertIn("止损距离超过 8%", workspace["pools"]["opportunity"]["results"][0]["trade_plan"]["forbidden_reasons"])
        self.assertNotIn("market_decision", workspace)
        self.assertNotIn("market_lines", workspace)
        self.assertNotIn("theme_lines", workspace)
        self.assertNotIn("theme_clusters", workspace)
        self.assertEqual([badge["label"] for badge in explanation["score_badges"][:4]], ["结构", "确认", "风险", "共振"])
        self.assertEqual(workspace["pools"]["bottom_div"]["count"], 1)
        self.assertEqual(workspace["sector_overview"][0]["sector"], "半导体")
        self.assertEqual(workspace["sector_overview"][0]["opportunity_count"], 1)
        self.assertEqual(workspace["sector_overview"][0]["bottom_div_count"], 1)
        self.assertEqual(workspace["market_structure_meta"]["mode"], "candidate_validated")
        self.assertEqual(workspace["sector_overview"][0]["structure_mode_label"], "候选验证")
        self.assertIn("候选验证", workspace["sector_overview"][0]["structure_source_label"])

    def test_collect_scan_workspace_caps_loaded_results_and_reports_total(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"
        frame.loc[10, "is_bottom_divergence"] = True

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
                            board_market_reader=lambda board_type, name=None, index_code=None, max_age_days=None: {
                                "type": "concept",
                                "name": "存储芯片",
                                "strength_score": 78,
                                "trend_label": "强势",
                                "ret_5": 4.5,
                                "ret_20": 8.0,
                                "latest_date": "2026-05-10",
                            } if board_type == "concept" and name == "存储芯片" else None,
                        )

        opportunity = workspace["pools"]["opportunity"]
        result = opportunity["results"][0]
        self.assertEqual(result["concepts"], ["存储芯片", "国企改革"])
        self.assertGreater(result["concept_score"], 0)
        self.assertEqual(result["concept_signal_count"], 2)
        self.assertEqual(result["concept_market_trend"], "强势")
        self.assertGreater(result["concept_market_boost"], 0)
        self.assertIn("概指", [badge["label"] for badge in result["explanation"]["score_badges"]])
        self.assertEqual(opportunity["concept_coverage"]["covered_count"], 1)
        self.assertEqual(opportunity["concept_coverage"]["coverage_rate"], 100.0)
        self.assertEqual(workspace["concept_overview"][0]["concept"], "存储芯片")
        self.assertEqual(workspace["concept_overview"][0]["opportunity_count"], 1)
        self.assertEqual(workspace["concept_overview"][0]["bottom_div_count"], 1)
        self.assertIn("structure_score", workspace["concept_overview"][0])
        self.assertIn("structure_source_label", workspace["concept_overview"][0])
        self.assertNotIn("theme_lines", workspace)

    def test_collect_scan_workspace_uses_profile_relation_evidence_in_market_structure(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        def board_market_reader(board_type, name=None, index_code=None, max_age_days=None):
            if board_type == "concept" and name == "储能":
                return {
                    "type": "concept",
                    "name": "储能",
                    "strength_score": 76,
                    "trend_label": "强势",
                    "ret_5": 3.0,
                    "ret_20": 8.0,
                    "latest_date": "2026-05-11",
                }
            return None

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
                            board_market_reader=board_market_reader,
                        )

        concept = next(item for item in workspace["concept_overview"] if item.get("concept") == "储能")
        result = workspace["pools"]["opportunity"]["results"][0]

        self.assertEqual(concept["relation_member_count"], 2)
        self.assertEqual(concept["relation_core_business_count"], 1)
        self.assertEqual(concept["relation_weak_association_count"], 1)
        self.assertEqual(concept["relation_verified_count"], 1)
        self.assertEqual(concept["relation_quality_label"], "主营确认")
        self.assertGreater(concept["relation_quality_score"], 50)
        self.assertEqual(result["concept_relation_quality_label"], "主营确认")
        self.assertIn("关系证据", concept["structure_source_label"])
        self.assertNotIn("market_lines", workspace)
        self.assertGreaterEqual(workspace["market_structure_meta"]["concepts"]["relation_verified_count"], 1)

    def test_build_scan_snapshot_records_strategy_version(self):
        frame = self._minimal_signal_frame(rows=12)
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")

        self.assertEqual(snapshot["version"], SCAN_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(snapshot["strategy_version"], SCAN_STRATEGY_VERSION)
        self.assertEqual(snapshot["strategy_meta"]["strategy_version"], SCAN_STRATEGY_VERSION)
        self.assertEqual(snapshot["strategy_meta"]["snapshot_schema_version"], SCAN_SNAPSHOT_SCHEMA_VERSION)

    def test_collect_scan_workspace_marks_legacy_strategy_snapshots(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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

    def test_collect_scan_workspace_ignores_replaced_legacy_snapshot_for_health(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        self.assertEqual(workspace["sector_overview"][0]["market_member_count"], 2)
        self.assertEqual(workspace["sector_overview"][0]["candidate_density"], 50.0)
        self.assertEqual(workspace["concept_overview"][0]["market_member_count"], 2)
        self.assertIn("width_label", workspace["concept_overview"][0])
        self.assertEqual(workspace["market_structure_meta"]["mode"], "market_universe")
        self.assertEqual(workspace["market_structure_meta"]["mode_label"], "全市场结构")
        self.assertEqual(workspace["sector_overview"][0]["structure_mode_label"], "市场结构")
        self.assertIn("score_confidence", result)
        self.assertEqual(result["score_confidence_label"], "待验证")

    def test_collect_scan_workspace_reports_expired_snapshot_health(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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

    def test_collect_scan_workspace_scores_sector_resonance_with_risk_penalty(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [1] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"
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
        self.assertEqual(overview["risk_count"], 2)
        self.assertEqual(opportunity["sector_opportunity_count"], 2)
        self.assertEqual(opportunity["sector_risk_count"], 2)
        self.assertIn("final_score", opportunity)
        calibration = workspace["resonance_calibration"]
        self.assertEqual(calibration["method"], "signal_history_proxy")
        self.assertEqual(
            sum(bucket["candidate_count"] for bucket in calibration["buckets"]),
            2,
        )
        self.assertTrue(any(bucket["sector_count"] == 1 for bucket in calibration["buckets"]))

    def test_collect_scan_workspace_applies_cached_board_market_context(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        def board_market_reader(board_type, name=None, index_code=None, max_age_days=None):
            if board_type == "industry" and name == "半导体":
                return {
                    "type": "industry",
                    "name": "半导体",
                    "strength_score": 82,
                    "trend_label": "强势",
                    "ret_5": 3.2,
                    "ret_20": 9.5,
                    "latest_date": "2026-05-08",
                }
            return None

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
                            board_market_reader=board_market_reader,
                        )

        overview = next(item for item in workspace["sector_overview"] if item.get("sector") == "半导体")
        result = workspace["pools"]["opportunity"]["results"][0]
        self.assertEqual(overview["market_trend_label"], "强势")
        self.assertIn("板块行情", overview["structure_source_label"])
        self.assertGreaterEqual(workspace["market_structure_meta"]["sectors"]["market_supported_count"], 1)
        self.assertEqual(result["sector_market_trend"], "强势")
        self.assertGreater(result["sector_market_boost"], 0)
        self.assertGreater(result["market_boost"], 0)
        self.assertGreater(result["final_score"], result["rank_score"])
        self.assertIn("板指强势", result["explanation"]["summary"])
        self.assertIn("板指", [badge["label"] for badge in result["explanation"]["score_badges"]])

    def test_collect_scan_workspace_reads_stale_board_market_cache_with_label(self):
        from stock_analyzer.market_boards import write_cached_board_market

        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            catalog_dir = tmp_path / "catalog"
            catalog_dir.mkdir(parents=True)
            profiles = {
                f"000{i:03d}": {"code": f"000{i:03d}", "name": f"样本{i}", "sector": f"A{i:02d}"}
                for i in range(30)
            }
            profiles["600063"] = {"code": "600063", "name": "示例股票", "sector": "半导体"}
            (catalog_dir / "stock_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")

            with patch("stock_analyzer.market_boards.BOARD_MARKET_CACHE_DIR", tmp_path / "board_market"):
                write_cached_board_market({
                    "type": "industry",
                    "name": "半导体",
                    "index_code": "半导体",
                    "source": "test",
                    "latest_date": "2026-05-11",
                    "strength_score": 82,
                    "trend_label": "强势",
                    "ret_5": 3.2,
                    "ret_20": 9.5,
                })
                with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", tmp_path / "snapshots"):
                    with patch("stock_analyzer.catalog.CATALOG_CACHE_DIR", catalog_dir):
                        with patch("stock_analyzer.market_boards.beijing_now", return_value=pd.Timestamp("2026-05-12 15:40")):
                            with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-12")):
                                snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-11", sector="半导体")
                                write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-11")
                                workspace = collect_scan_workspace(start_date="2025-04-29")

        overview = next(item for item in workspace["sector_overview"] if item.get("sector") == "半导体")
        result = workspace["pools"]["opportunity"]["results"][0]
        self.assertEqual(overview["market_trend_label"], "强势")
        self.assertTrue(overview["market_cache_stale"])
        self.assertIn("旧行情", overview["structure_source_label"])
        self.assertTrue(result["sector_market_cache_stale"])
        self.assertGreaterEqual(workspace["market_structure_meta"]["sectors"]["market_supported_count"], 1)

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
                            workspace = collect_scan_workspace(start_date="2025-04-29")
                            next_open_workspace = collect_scan_workspace(
                                start_date="2025-04-29",
                                replay_entry_model="next_open",
                            )

        replay = workspace["replay_calibration"]
        next_open_replay = next_open_workspace["replay_calibration"]
        result = workspace["pools"]["opportunity"]["results"][0]
        watch_bucket = next(bucket for bucket in replay["buckets"] if bucket["key"] == "watch")
        next_open_watch_bucket = next(bucket for bucket in next_open_replay["buckets"] if bucket["key"] == "watch")
        self.assertEqual(replay["method"], "historical_snapshot_replay")
        self.assertEqual(replay["entry_model"], "event_close")
        self.assertEqual(watch_bucket["horizons"]["5"]["sample_count"], 1)
        self.assertEqual(watch_bucket["horizons"]["5"]["avg_ret"], 50.0)
        self.assertEqual(next_open_replay["entry_model"], "next_open")
        self.assertEqual(next_open_watch_bucket["horizons"]["5"]["sample_count"], 1)
        self.assertEqual(next_open_watch_bucket["horizons"]["5"]["avg_ret"], 45.45)
        self.assertEqual(result["score_confidence"]["replay_5d_sample_count"], 1)
        self.assertEqual(result["score_confidence"]["replay_5d_avg_ret"], 50.0)
        self.assertEqual(result["score_confidence"]["replay_5d_win_rate"], 100.0)
        self.assertIn("胜率 100.0%", result["score_confidence"]["basis"])

    def test_scan_workspace_api_returns_cached_pool_summary(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
        self.assertEqual(len(payload["resonance_calibration"]["buckets"]), 4)
        self.assertIn("replay_calibration", payload)
        self.assertEqual(payload["replay_calibration"]["horizons"], [3, 5, 10])
        self.assertEqual(payload["snapshot_meta"]["health"], "healthy")
        self.assertEqual(payload["snapshot_meta"]["latest_snapshot_day"], "2026-05-10")

    def test_scan_workspace_api_can_defer_replay_calibration_for_lite_load(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

        with TemporaryDirectory() as tmp_dir:
            with patch("stock_analyzer.scan_snapshot.SNAPSHOT_DIR", Path(tmp_dir)):
                with patch("stock_analyzer.scan_snapshot.beijing_now", return_value=pd.Timestamp("2026-05-11")):
                    snapshot = build_scan_snapshot("600063", "示例股票", frame, snapshot_day="2026-05-10")
                    write_scan_snapshot(snapshot, start_date="2025-04-29", snapshot_day="2026-05-10")
                    client = app.app.test_client()
                    lite_response = client.get("/api/scan_workspace?lite=1")
                    full_response = client.get("/api/scan_workspace")

        lite_payload = lite_response.get_json()
        full_payload = full_response.get_json()
        self.assertEqual(lite_response.status_code, 200)
        self.assertEqual(full_response.status_code, 200)
        self.assertEqual(lite_payload["replay_calibration"]["method"], "deferred")
        self.assertEqual(lite_payload["replay_calibration"]["entry_model"], "event_close")
        self.assertEqual(lite_payload["replay_calibration"]["horizons"], [3, 5, 10])
        self.assertEqual(lite_payload["market_structure_meta"]["mode"], "candidate_validated")
        self.assertEqual(full_payload["replay_calibration"]["method"], "historical_snapshot_replay")

    def test_scan_workspace_api_honors_result_limit(self):
        frame = self._minimal_signal_frame(rows=12)
        frame["date"] = pd.date_range("2026-04-29", periods=12, freq="D")
        frame["composite_setup_score"] = [2] * 12
        frame["composite_confirm_score"] = [3] * 12
        frame["composite_risk_score"] = [0] * 12
        frame["composite_watch"] = [False] * 12
        frame.loc[11, "composite_entry"] = True
        frame.loc[11, "composite_entry_type"] = "pullback"
        frame.loc[11, "composite_entry_reason"] = "回踩确认"

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
