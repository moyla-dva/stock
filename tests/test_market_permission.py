import unittest

from stock_analyzer.market_permission import build_v2_environment_permission


class CandidateMarketContextBoundaryTest(unittest.TestCase):
    def test_sector_and_concept_context_do_not_change_stock_macro_permission(self):
        state = {
            "scan_type": "opportunity",
            "v2_permission": "pullback_allowed",
            "v2_state_model": {
                "permission": "pullback_allowed",
                "state": "entry_pullback",
                "signal": "C回",
                "facts": {
                    "macro_tide": {
                        "available": True,
                        "summary": "个股宏观条件通过",
                        "ma60": {"available": True, "up": True},
                    },
                },
            },
            "sector_market_score": 100,
            "concept_market_score": 100,
            "market_boost": 10,
            "v2_sector_permission": "forbidden",
            "v2_concept_permission": "forbidden",
        }

        permission = build_v2_environment_permission(state)

        self.assertEqual(permission["v2_environment_permission"], "allowed")
        self.assertEqual(permission["v2_effective_permission"], "pullback_allowed")
        self.assertEqual(permission["v2_sector_permission"], "not_used")
        self.assertEqual(permission["v2_concept_permission"], "not_used")

    def test_stock_macro_veto_is_unchanged_by_strong_board_context(self):
        state = {
            "scan_type": "opportunity",
            "v2_permission": "breakout_allowed",
            "v2_state_model": {
                "permission": "breakout_allowed",
                "state": "entry_breakout",
                "signal": "C突",
                "facts": {
                    "macro_tide": {
                        "available": True,
                        "ma250": {"available": True, "above": False},
                        "weekly_macd": {"available": True},
                    },
                },
            },
            "sector_market_score": 100,
            "concept_market_score": 100,
            "market_boost": 100,
        }

        permission = build_v2_environment_permission(state)

        self.assertEqual(permission["v2_macro_veto_permission"], "forbidden")
        self.assertEqual(permission["v2_environment_permission"], "forbidden")
        self.assertEqual(permission["v2_effective_permission"], "environment_blocked")


if __name__ == "__main__":
    unittest.main()
