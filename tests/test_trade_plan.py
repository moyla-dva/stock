import unittest

import pandas as pd

from stock_analyzer.market_permission import build_stock_trade_permission
from stock_analyzer.technical_structures import build_williams_clock
from stock_analyzer.trade_plan import build_trade_plan


def _base_frame(rows=12):
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    close = [10.0 + idx * 0.08 for idx in range(rows)]
    frame = pd.DataFrame({
        "date": dates,
        "open": [value - 0.05 for value in close],
        "high": [value + 0.25 for value in close],
        "low": [value - 0.35 for value in close],
        "close": close,
        "volume": [1000] * rows,
        "ma20": [9.8 + idx * 0.06 for idx in range(rows)],
        "boll_mid": [10.0] * rows,
        "upper_band": [10.8] * rows,
        "lower_band": [9.2] * rows,
        "ma20_up": [True] * rows,
        "trend_ok": [True] * rows,
        "composite_setup_score": [2] * rows,
        "composite_confirm_score": [4] * rows,
        "composite_risk_score": [1] * rows,
        "composite_watch": [True] * rows,
        "composite_entry": [False] * rows,
        "composite_risk": [False] * rows,
        "composite_risk_warn": [False] * rows,
        "composite_exit": [False] * rows,
        "composite_entry_type": [""] * rows,
        "composite_entry_reason": [""] * rows,
    })
    return frame


class TradePlanTest(unittest.TestCase):
    def test_permission_allows_execution_only_after_trigger(self):
        frame = _base_frame()
        frame.loc[len(frame) - 1, "composite_entry"] = True
        frame.loc[len(frame) - 1, "composite_entry_type"] = "breakout"

        permission = build_stock_trade_permission(frame, context={"alignment": "structure"})

        self.assertTrue(permission["can_open"])
        self.assertEqual(permission["mode"], "execution_ready")
        self.assertEqual(permission["scores"]["confirm"], 4)

    def test_trade_plan_blocks_when_risk_overrides_signal(self):
        frame = _base_frame()
        frame.loc[len(frame) - 1, "composite_entry"] = True
        frame.loc[len(frame) - 1, "composite_risk_score"] = 4
        frame.loc[len(frame) - 1, "composite_exit"] = True

        plan = build_trade_plan(frame)

        self.assertEqual(plan["status"], "risk_control")
        self.assertFalse(plan["permission"]["can_open"])
        self.assertIn("风险", plan["status_label"])

    def test_trade_plan_adds_stop_and_r_multiple_for_ready_setup(self):
        frame = _base_frame()
        frame.loc[len(frame) - 1, "composite_entry"] = True
        frame.loc[len(frame) - 1, "composite_entry_type"] = "pullback"
        frame.loc[len(frame) - 1, "composite_entry_reason"] = "回踩确认 / 趋势有效"

        plan = build_trade_plan(frame, context={"alignment": "structure"})

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["entry"]["state"], "triggered")
        self.assertIsNotNone(plan["stop"]["price"])
        self.assertGreater(plan["targets"]["r2"], plan["latest_price"])
        self.assertNotIn("mainline_context", plan)
        self.assertIn("每一笔加仓单独管理止损", plan["position"]["rules"])

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
