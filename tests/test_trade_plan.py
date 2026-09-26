import unittest
from unittest.mock import patch

import pandas as pd

from stock_analyzer.c_signal_v2_facts import build_c_signal_v2_facts
from stock_analyzer.technical_structures import build_williams_clock
from stock_analyzer.trade_plan import build_trade_plan, evaluate_v2_plan_gate


def _base_frame(rows=25):
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    frame = pd.DataFrame({
        "date": dates,
        "open": [9.95] * rows,
        "high": [10.15] * rows,
        "low": [9.85] * rows,
        "close": [10.0] * rows,
        "volume": [1000] * rows,
        "ma20": [10.0] * rows,
        "boll_mid": [10.0] * rows,
        "upper_band": [10.8] * rows,
        "lower_band": [9.2] * rows,
        "return_pct": [0.0] * rows,
        "volume_ratio": [1.5] * rows,
    })
    return frame


def _v2_breakout_frame(rows=25):
    """10日箱体 10.4-10.6，第5日留 13.0 前高作上方阻力，末日重新站上箱体上沿。

    突破日收盘 11.1 高于 previous_upper 10.6（P2-4 口径）但低于 20 日前高 13.0，
    用于验证"二次突破"不再被含当日窗口的参考位吞掉。
    """
    frame = _base_frame(rows=rows)
    frame.loc[:, ["open", "high", "low", "close", "ma20"]] = [
        [10.5, 10.6, 10.4, 10.5, 10.5] for _ in range(rows)
    ]
    frame.loc[5, ["open", "high", "low", "close"]] = [12.6, 13.0, 12.5, 12.8]
    frame.loc[5, "volume"] = 1500
    last = rows - 1
    frame.loc[last, ["open", "high", "low", "close"]] = [10.7, 11.2, 10.65, 11.1]
    frame.loc[last, "volume"] = 3000
    return frame


def _v2_entry_then_crash_frame(rows=25):
    frame = _base_frame(rows=rows)
    frame.loc[22, ["open", "high", "low", "close"]] = [10.05, 10.7, 10.0, 10.6]
    frame.loc[23, ["open", "high", "low", "close"]] = [10.4, 10.4, 9.8, 9.9]
    frame.loc[24, ["open", "high", "low", "close"]] = [9.8, 9.9, 8.8, 9.0]
    return frame


class TradePlanTest(unittest.TestCase):
    @patch(
        "stock_analyzer.c_signal_v2.evaluate_macro_entry_blocks",
        new=lambda *args, **kwargs: {
            "block_reasons": [],
            "warnings": [],
            "macro_available": True,
            "macro_summary": "",
        },
    )
    def test_permission_allows_execution_only_after_trigger(self):
        frame = _v2_breakout_frame()

        plan = build_trade_plan(frame, context={"alignment": "structure"})

        self.assertEqual(plan["permission"]["source"], "c_signal_v2_permission")
        self.assertTrue(plan["permission"]["can_open"])
        self.assertEqual(plan["permission"]["mode"], "execution_ready")
        self.assertLessEqual(plan["permission"]["scores"]["risk"], 2)

        flat_plan = build_trade_plan(_base_frame(), context={"alignment": "structure"})
        self.assertFalse(flat_plan["permission"]["can_open"])
        self.assertEqual(flat_plan["status"], "waiting")

    def test_v2_breakout_trigger_fires_on_rectangle_upper_recovery(self):
        frame = _v2_breakout_frame()

        facts = build_c_signal_v2_facts(frame)

        self.assertTrue(facts["setup"]["breakout_trigger"])
        self.assertTrue(facts["setup"]["prior_breakout"])
        self.assertEqual(facts["structure"]["active_rectangle"]["family"], "short")

    def test_v2_risk_facts_break_uses_structure_before_today(self):
        frame = _v2_entry_then_crash_frame()

        facts = build_c_signal_v2_facts(frame)

        self.assertGreaterEqual(facts["risk"]["risk_break_score"], 1)
        self.assertTrue(facts["risk"]["has_risk"])

    def test_trade_plan_blocks_when_risk_overrides_signal(self):
        frame = _v2_entry_then_crash_frame()

        plan = build_trade_plan(frame)

        self.assertEqual(plan["status"], "risk_control")
        self.assertFalse(plan["permission"]["can_open"])
        self.assertIn("风险", plan["status_label"])

    def test_trade_plan_keeps_hold_permission_for_strong_resistance_scale_out(self):
        frame = _base_frame()
        facts = {
            "scores": {"setup": 0, "confirm": 0, "risk": 1},
            "setup": {},
            "structure": {},
            "trigger": {},
            "risk": {},
            "macro_tide": {},
            "exit_gate": {
                "action": "scale_out",
                "summary": "触及核心强阻，先减仓保护利润",
            },
        }

        plan = build_trade_plan(frame, context={"c_signal_v2_facts": facts})

        self.assertEqual(plan["status"], "risk_control")
        self.assertEqual(plan["permission"]["permission"], "risk_only")
        self.assertEqual(plan["permission"]["mode"], "risk_control")
        self.assertTrue(plan["permission"]["can_hold"])
        self.assertFalse(plan["permission"]["can_open"])
        self.assertIn("收益保护", plan["detail"])

    @patch(
        "stock_analyzer.c_signal_v2.evaluate_macro_entry_blocks",
        new=lambda *args, **kwargs: {
            "block_reasons": [],
            "warnings": [],
            "macro_available": True,
            "macro_summary": "",
        },
    )
    def test_trade_plan_adds_stop_and_r_multiple_for_ready_setup(self):
        frame = _v2_breakout_frame()

        plan = build_trade_plan(frame, context={"alignment": "structure"})

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["entry"]["state"], "triggered")
        self.assertIsNotNone(plan["stop"]["price"])
        self.assertGreater(plan["targets"]["r2"], plan["latest_price"])
        self.assertNotIn("mainline_context", plan)
        self.assertIn("每一笔加仓单独管理止损", plan["position"]["rules"])

    @patch(
        "stock_analyzer.c_signal_v2.evaluate_macro_entry_blocks",
        new=lambda *args, **kwargs: {
            "block_reasons": [],
            "warnings": [],
            "macro_available": True,
            "macro_summary": "",
        },
    )
    def test_trade_plan_calculates_position_from_account_risk(self):
        frame = _v2_breakout_frame()

        plan = build_trade_plan(
            frame,
            context={
                "alignment": "structure",
                "account_size": 100000,
                "risk_pct": 3,
                "target_price": 13,
            },
        )

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["position"]["risk_pct"], 3)
        self.assertEqual(plan["position"]["risk_budget_amount"], 3000)
        self.assertEqual(plan["position"]["lot_size"], 100)
        self.assertGreater(plan["position"]["suggested_shares"], 0)
        self.assertLessEqual(plan["position"]["estimated_capital"], 30000)
        self.assertEqual(plan["position"]["capped_by"], "max_capital_pct")
        self.assertIn(plan["risk_reward"]["status"], {"pass", "ideal"})
        self.assertGreaterEqual(plan["risk_reward"]["ratio"], 2)

    def test_trade_plan_defaults_single_trade_risk_to_two_percent(self):
        frame = _v2_breakout_frame()

        plan = build_trade_plan(
            frame,
            context={
                "alignment": "structure",
                "account_size": 100000,
                "target_price": 13,
            },
        )

        self.assertEqual(plan["position"]["risk_pct"], 2)
        self.assertEqual(plan["position"]["risk_budget_amount"], 2000)
        self.assertIn("首笔风险预算默认 2%", plan["position"]["rules"][1])

    def test_trade_plan_blocks_when_target_is_below_two_r(self):
        frame = _v2_breakout_frame()

        plan = build_trade_plan(
            frame,
            context={
                "alignment": "structure",
                "account_size": 100000,
                "risk_pct": 3,
                "target_price": 11,
            },
        )

        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(plan["risk_reward"]["status"], "fail")
        self.assertIn("收益风险比低于 2:1", plan["forbidden_reasons"])

    def test_v2_plan_gate_blocks_missing_or_wide_stop(self):
        missing_stop = evaluate_v2_plan_gate(
            entry_type="attack",
            entry_price=10,
            stop_price=None,
            target_price=12,
        )
        wide_stop = evaluate_v2_plan_gate(
            entry_type="attack",
            entry_price=10,
            stop_price=9,
            target_price=13,
        )

        self.assertEqual(missing_stop["status"], "blocked")
        self.assertIn("缺少结构止损价", missing_stop["block_reasons"])
        self.assertEqual(wide_stop["status"], "blocked")
        self.assertIn("止损距离超过 8%", wide_stop["block_reasons"])

    def test_v2_plan_gate_requires_two_r_before_ready(self):
        low_reward = evaluate_v2_plan_gate(
            entry_type="attack",
            entry_price=10,
            stop_price=9.5,
            target_price=10.8,
        )
        ready = evaluate_v2_plan_gate(
            entry_type="attack",
            entry_price=10,
            stop_price=9.5,
            target_price=11.5,
        )

        self.assertEqual(low_reward["status"], "blocked")
        self.assertIn("收益风险比低于 2:1", low_reward["block_reasons"])
        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["risk_reward_ratio"], 3)

    def test_v2_plan_gate_blocks_breakout_chase_risk(self):
        gate = evaluate_v2_plan_gate(
            entry_type="breakout",
            entry_price=10,
            stop_price=9.6,
            target_price=11,
            context={
                "return_pct": 6.5,
                "ma20_deviation_pct": 10.5,
                "risk_heat_score": 3,
                "volume_ratio": 3.2,
            },
        )

        self.assertEqual(gate["status"], "blocked")
        self.assertIn("extended_return", gate["execution_risk_flags"])
        self.assertIn("ma20_extended", gate["execution_risk_flags"])
        self.assertIn("heat_extended", gate["execution_risk_flags"])
        self.assertIn("量比过大，注意冲高回落风险", gate["warnings"])

    def test_v2_plan_gate_keeps_pullback_heat_as_warning(self):
        gate = evaluate_v2_plan_gate(
            entry_type="pullback",
            entry_price=10,
            stop_price=9.6,
            target_price=11,
            context={"risk_heat_score": 3, "volume_ratio": 2.8},
        )

        self.assertEqual(gate["status"], "ready")
        self.assertTrue(gate["ready"])
        self.assertIn("pullback_heat_warning", gate["execution_risk_flags"])
        self.assertTrue(gate["warnings"])

    def test_trade_plan_marks_breakout_execution_constraints(self):
        frame = _v2_breakout_frame()
        last = len(frame) - 1
        frame.loc[last, "return_pct"] = 6.2
        frame.loc[last, "ma20"] = frame.loc[last, "close"] / 1.11
        frame.loc[last, "volume_ratio"] = 3.1

        plan = build_trade_plan(frame, context={"alignment": "structure"})

        keys = [item["key"] for item in plan["execution_constraints"]]
        self.assertIn("next_open_chase", keys)
        self.assertIn("breakout_day_extended", keys)
        self.assertIn("ma20_extended", keys)
        self.assertIn("volume_ratio_outside_preferred", keys)

    def test_trade_plan_marks_attack_execution_constraints(self):
        frame = _v2_breakout_frame()
        last = len(frame) - 1
        frame.loc[last, "return_pct"] = 6.2
        frame.loc[last, "ma20"] = frame.loc[last, "close"] / 1.11
        frame.loc[last, "volume_ratio"] = 3.1
        facts = {
            "trigger": {"attack_day": True, "summary": "攻击日触发"},
            "risk": {"risk_heat_score": 3},
        }
        plan = build_trade_plan(
            frame,
            context={
                "alignment": "structure",
                "c_signal_v2_facts": facts,
                "v2_permission_model": {
                    "permission": "attack_allowed",
                    "permission_label": "允许攻击",
                    "can_open": True,
                    "next_action": "按计划执行",
                    "plan_gate": {
                        "entry_type": "attack",
                        "stop_price": frame.loc[last, "low"],
                        "target_price": 13.0,
                    },
                },
            },
        )

        self.assertEqual(plan["entry"]["signal_type"], "attack")
        keys = [item["key"] for item in plan["execution_constraints"]]
        self.assertIn("next_open_chase", keys)
        self.assertIn("breakout_day_extended", keys)
        self.assertIn("ma20_extended", keys)
        self.assertIn("heat_score_high", keys)
        self.assertIn("volume_ratio_outside_preferred", keys)

    def test_williams_clock_marks_low_bandwidth_as_countdown_not_direction(self):
        rows = 60
        bandwidth = [10.0] * 50 + [1.0] * 10
        volume = [1000] * 50 + [500] * 10
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=rows, freq="D"),
            "close": [100.0] * rows,
            "volume": volume,
            "boll_mid": [100.0] * rows,
            "upper_band": [100.0 + value / 2 for value in bandwidth],
            "lower_band": [100.0 - value / 2 for value in bandwidth],
        })

        clock = build_williams_clock(frame)

        self.assertEqual(clock["state"], "countdown")
        self.assertEqual(clock["direction"], "unknown")
        self.assertGreaterEqual(clock["metrics"]["compression_score"], 80)
        self.assertGreaterEqual(clock["metrics"]["volume_dryness_days"], 5)


if __name__ == "__main__":
    unittest.main()
