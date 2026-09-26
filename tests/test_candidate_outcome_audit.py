import unittest

import pandas as pd

from scripts.audit_candidate_outcomes import (
    _pearson,
    _rankdata,
    _summary,
    evaluate_candidate_frame,
)


class CandidateOutcomeAuditTest(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "date": pd.to_datetime([
                "2026-09-18",
                "2026-09-21",
                "2026-09-22",
                "2026-09-23",
            ]),
            "open": [9.8, 10.0, 10.5, 10.8],
            "close": [10.0, 10.4, 10.7, 11.0],
            "high": [10.1, 10.6, 10.9, 11.2],
            "low": [9.7, 9.9, 10.2, 10.6],
        })

    def test_next_open_horizon_includes_entry_session(self):
        outcomes = evaluate_candidate_frame(
            self.frame,
            as_of="2026-09-18",
            horizons=(1, 3, 5),
        )

        self.assertEqual(set(outcomes), {1, 3})
        self.assertEqual(outcomes[1]["entry_date"], "2026-09-21")
        self.assertEqual(outcomes[1]["exit_date"], "2026-09-21")
        self.assertAlmostEqual(outcomes[1]["return_pct"], 4.0)
        self.assertEqual(outcomes[3]["exit_date"], "2026-09-23")
        self.assertAlmostEqual(outcomes[3]["mfe_pct"], 12.0)
        self.assertAlmostEqual(outcomes[3]["mae_pct"], -1.0)

    def test_missing_future_bar_is_not_fabricated(self):
        self.assertEqual(
            evaluate_candidate_frame(
                self.frame,
                as_of="2026-09-23",
                horizons=(1,),
            ),
            {},
        )

    def test_summary_ignores_non_finite_values(self):
        summary = _summary([
            {"return_pct": 2, "mfe_pct": 3, "mae_pct": -1},
            {"return_pct": float("nan"), "mfe_pct": 4, "mae_pct": -2},
            {"return_pct": -1, "mfe_pct": 1, "mae_pct": -3},
        ])

        self.assertEqual(summary["evaluated_count"], 2)
        self.assertEqual(summary["win_rate_pct"], 50.0)
        self.assertEqual(summary["mean_return_pct"], 0.5)

    def test_rank_correlation_helpers_handle_ties(self):
        self.assertEqual(_rankdata([10, 20, 20, 40]), [1.0, 2.5, 2.5, 4.0])
        self.assertAlmostEqual(_pearson([1, 2, 3], [3, 2, 1]), -1.0)


if __name__ == "__main__":
    unittest.main()
