import unittest
from datetime import date
from unittest.mock import patch

import app
from stock_analyzer.single_stock_read_model import SingleStockAnalysis


def _payload():
    return {
        "stock_code": "600001",
        "stock_name": "样本A (600001)",
        "stock_sector": "半导体",
        "stock_concepts": ["存储芯片"],
        "tag_profile": {"confidence": 0.9},
        "dates": ["2026-09-21", "2026-09-22"],
        "k_data": [[10.0, 10.2, 9.9, 10.3], [10.2, 10.5, 10.1, 10.6]],
        "ma20_data": [9.8, 9.9],
        "vwap_data": [10.0, 10.3],
        "bull_power_data": [0.1, 0.2],
        "bear_power_data": [-0.1, -0.05],
        "williams_r_data": [50, 40],
        "custom_data": [0.1, 0.2],
        "dif_data": [0.01, 0.02],
        "dea_data": [0.0, 0.01],
        "macd_data": [0.02, 0.02],
        "mark_points_v2": [{"date": "2026-09-22", "signalCode": "v2_breakout"}],
        "v2_event_lookback": 60,
        "score_summary": {"setup": 3, "confirm": 2, "risk": 0},
        "signal_definitions": {"v2_breakout": {"label": "C突"}},
        "c_signal_v2_state": {
            "state": "trigger_plan_ready",
            "facts": {
                "structure": {
                    "summary": "箱体突破",
                    "normalized_bars": [{"close": 10.5}] * 20,
                    "rectangle_candidates": [{"upper": 10.5}] * 5,
                },
                "trigger": {"breaks_prev_high": True},
            },
        },
        "trade_plan": {"status": "ready"},
        "multi_timeframes": {"daily": {"available": True}},
        "event_stats": {
            "v2": {"horizon": 5, "entry_model": "event_close", "by_signal": {}},
        },
    }


class SingleStockReadModelTest(unittest.TestCase):
    def test_rejects_non_mapping_payload(self):
        with self.assertRaisesRegex(ValueError, "must be an object"):
            SingleStockAnalysis.from_payload([])

    def test_data_revision_accepts_date_like_values(self):
        payload = _payload()
        payload["dates"] = [date(2026, 9, 21), date(2026, 9, 22)]

        model = SingleStockAnalysis.from_payload(payload).to_dict()

        self.assertTrue(model["identity"]["data_revision"].startswith("sha256:"))

    def test_groups_existing_payload_without_recomputing_signals(self):
        model = SingleStockAnalysis.from_payload(_payload(), refresh_requested=True).to_dict()

        self.assertEqual(model["schema_version"], 2)
        self.assertEqual(model["identity"]["code"], "600001")
        self.assertEqual(model["identity"]["as_of"], "2026-09-22")
        self.assertTrue(model["identity"]["data_revision"].startswith("sha256:"))
        self.assertEqual(model["market_data"]["latest_bar"], {
            "at": "2026-09-22",
            "open": 10.2,
            "close": 10.5,
            "low": 10.1,
            "high": 10.6,
        })
        self.assertEqual(model["chart"]["candle_fields"], ["open", "close", "low", "high"])
        self.assertEqual(model["signal_observations"]["events"][0]["signalCode"], "v2_breakout")
        structure = model["current_state"]["facts"]["structure"]
        self.assertNotIn("normalized_bars", structure)
        self.assertNotIn("rectangle_candidates", structure)
        self.assertEqual(model["conditional_plan"]["status"], "ready")
        self.assertEqual(model["event_study"]["results"]["v2"]["entry_model"], "event_close")
        self.assertTrue(model["data_quality"]["refresh_requested"])

    def test_uses_upstream_market_data_identity_when_available(self):
        payload = _payload()
        payload["data_identity"] = {
            "bar_state": "preview",
            "data_source": "tencent_direct+tencent_realtime",
            "data_revision": "sha256:upstream",
            "generated_at": "2026-09-22T10:30:00+08:00",
            "cache_status": "realtime_merge",
            "calendar_id": "XSHG",
            "calendar_revision": "sha256:calendar",
            "calendar_evidence_level": "provider",
        }

        model = SingleStockAnalysis.from_payload(payload).to_dict()

        self.assertEqual(model["identity"]["bar_state"], "preview")
        self.assertEqual(
            model["identity"]["data_source"],
            "tencent_direct+tencent_realtime",
        )
        self.assertEqual(model["identity"]["data_revision"], "sha256:upstream")
        self.assertEqual(model["identity"]["calendar_id"], "XSHG")
        self.assertEqual(model["identity"]["calendar_revision"], "sha256:calendar")
        self.assertEqual(model["data_quality"]["cache_status"], "realtime_merge")
        self.assertEqual(model["data_quality"]["issues"], [])

    @patch("app.get_stock_profile", return_value={
        "name": "样本A",
        "sector": "半导体",
        "concepts": ["存储芯片"],
    })
    @patch("app.fetch_and_process_data", return_value=_payload())
    def test_opt_in_api_returns_stable_grouped_contract(self, mock_fetch, _mock_profile):
        response = app.app.test_client().get(
            "/api/single_stock_analysis?code=600001&refresh=1"
        )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["identity"]["code"], "600001")
        self.assertEqual(payload["profile"]["sector"], "半导体")
        self.assertIn("chart", payload)
        self.assertIn("current_state", payload)
        self.assertNotIn("k_data", payload)
        mock_fetch.assert_called_once_with(
            "600001",
            include_legacy_chart=False,
            force_refresh=True,
        )

    def test_opt_in_api_returns_structured_invalid_code_error(self):
        response = app.app.test_client().get(
            "/api/single_stock_analysis?code=invalid"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_stock_code")


if __name__ == "__main__":
    unittest.main()
