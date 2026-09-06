import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from stock_analyzer.market_breadth import apply_market_breadth_to_overview


class MarketBreadthTest(unittest.TestCase):
    def _write_history(self, cache_dir, code, closes):
        rows = []
        for index, close in enumerate(closes):
            rows.append({
                "date": pd.Timestamp("2026-04-20") + pd.Timedelta(days=index),
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1000,
            })
        pd.DataFrame(rows).to_csv(Path(cache_dir) / f"{code}_20250429_20260511_qfq.csv", index=False)

    def test_apply_market_breadth_uses_cached_constituent_histories(self):
        with TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            self._write_history(cache_dir, "600001", [10 + i * 0.1 for i in range(22)])
            self._write_history(cache_dir, "600002", [12 - i * 0.1 for i in range(22)])
            profile_cache = {
                "600001": {"sector": "半导体", "concepts": ["芯片"]},
                "600002": {"sector": "半导体", "concepts": ["芯片"]},
            }
            sector_overview = [{
                "sector": "半导体",
                "sector_score": 80,
                "signal_count": 2,
                "avg_rank": 70,
                "width_label": "有宽度",
                "width_score": 30,
            }]
            concept_overview = [{
                "concept": "芯片",
                "concept_score": 75,
                "signal_count": 2,
                "avg_rank": 65,
                "width_label": "有宽度",
                "width_score": 28,
            }]

            apply_market_breadth_to_overview(
                sector_overview,
                concept_overview,
                profile_cache,
                cache_dir=cache_dir,
            )

        self.assertEqual(sector_overview[0]["breadth_sample_count"], 2)
        self.assertEqual(sector_overview[0]["breadth_up_rate"], 50.0)
        self.assertEqual(sector_overview[0]["breadth_ma20_rate"], 50.0)
        self.assertEqual(sector_overview[0]["width_label"], "偏强")
        self.assertEqual(concept_overview[0]["breadth_sample_count"], 2)


if __name__ == "__main__":
    unittest.main()
