import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from stock_analyzer.providers.market_reference import (
    build_exchange_universe,
    load_akshare_bundled_calendar,
    load_exchange_validated_calendar,
)


class MarketReferenceProviderTest(unittest.TestCase):
    def test_reads_bundled_calendar_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "file_fold").mkdir()
            (root / "file_fold" / "calendar.json").write_text(
                json.dumps(["20260922", "20260921", "20260922"]),
                encoding="utf-8",
            )
            module_path = root / "__init__.py"
            module_path.write_text("", encoding="utf-8")
            fake = SimpleNamespace(__file__=str(module_path), __version__="test")

            payload = load_akshare_bundled_calendar(fake)

        self.assertEqual(payload.sessions, ("20260921", "20260922"))
        self.assertEqual(payload.source, "akshare-test:bundled-sina-calendar")
        self.assertEqual(payload.evidence_level, "provider")

    def test_historical_universe_filters_listing_and_delisting_dates(self):
        sh_main = pd.DataFrame([
            {"证券代码": "600001", "证券简称": "A", "上市日期": "2000-01-01"},
            {"证券代码": "600002", "证券简称": "Future", "上市日期": "2027-01-01"},
        ])
        sh_star = pd.DataFrame([
            {"证券代码": "688001", "证券简称": "Star", "上市日期": "2020-01-01"},
        ])
        sz = pd.DataFrame([
            {"A股代码": "000001", "A股简称": "SZ", "A股上市日期": "1991-01-01"},
        ])
        bse = pd.DataFrame([
            {"证券代码": "830001", "证券简称": "BSE", "上市日期": "2021-11-15"},
        ])
        sh_delisted = pd.DataFrame([
            {
                "公司代码": "600003",
                "公司简称": "Old A",
                "上市日期": "1995-01-01",
                "暂停上市日期": "2026-10-01",
            },
            {
                "公司代码": "600004",
                "公司简称": "Old B",
                "上市日期": "1995-01-01",
                "暂停上市日期": "2026-01-01",
            },
        ])
        sz_delisted = pd.DataFrame(columns=["证券代码", "证券简称", "上市日期", "终止上市日期"])
        fake = SimpleNamespace(
            __version__="test",
            stock_info_sh_name_code=lambda symbol: sh_main if symbol == "主板A股" else sh_star,
            stock_info_sz_name_code=lambda symbol: sz,
            stock_info_bj_name_code=lambda: bse,
            stock_info_sh_delist=lambda symbol: sh_delisted,
            stock_info_sz_delist=lambda symbol: sz_delisted,
        )

        payload = build_exchange_universe(
            "2026-09-22",
            fake,
            observed_on="2026-09-23",
        )

        codes = {item["code"] for item in payload.members}
        self.assertEqual(codes, {"000001", "600001", "600003", "688001", "830001"})
        self.assertEqual(payload.coverage_status, "partial")
        self.assertEqual(payload.evidence_level, "provider-derived")
        self.assertTrue(any("BSE delisted history" in item for item in payload.warnings))
        self.assertEqual(
            payload.coverage["delisting_history"]["BSE"]["status"],
            "missing",
        )
        self.assertEqual(
            payload.coverage["security_name_history"]["ALL"]["status"],
            "missing",
        )
        self.assertEqual(
            payload.coverage["security_name_history"]["ALL"]["impact"],
            "display",
        )
        old = next(item for item in payload.members if item["code"] == "600003")
        self.assertEqual(old["delisting_date"], "2026-10-01")
        self.assertEqual(old["member_source"], "sse_delisted")

    def test_current_universe_fails_closed_when_bse_membership_is_unavailable_or_invalid(self):
        sh = pd.DataFrame([
            {"证券代码": "600001", "证券简称": "A", "上市日期": "2000-01-01"},
        ])
        sz = pd.DataFrame([
            {"A股代码": "000001", "A股简称": "SZ", "A股上市日期": "1991-01-01"},
        ])
        for bse in (pd.DataFrame(), pd.DataFrame([{"unexpected": "830001"}])):
            with self.subTest(columns=list(bse.columns)):
                fake = SimpleNamespace(
                    __version__="test",
                    stock_info_sh_name_code=lambda symbol: sh,
                    stock_info_sz_name_code=lambda symbol: sz,
                    stock_info_bj_name_code=lambda: bse,
                )

                expected_message = (
                    "required universe source returned no rows: BSE current list"
                    if bse.empty
                    else "required universe source produced no valid membership rows: BSE current list"
                )
                with self.assertRaisesRegex(RuntimeError, expected_message):
                    build_exchange_universe("2026-09-23", fake, observed_on="2026-09-23")

    def test_official_schedule_replaces_provider_year_and_adds_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "file_fold").mkdir()
            (root / "file_fold" / "calendar.json").write_text(
                json.dumps(["20251231", "20260102", "20261231"]),
                encoding="utf-8",
            )
            module_path = root / "__init__.py"
            module_path.write_text("", encoding="utf-8")
            fake = SimpleNamespace(__file__=str(module_path), __version__="test")

            payload = load_exchange_validated_calendar(fake)

        self.assertNotIn("20260102", payload.sessions)
        self.assertIn("20260105", payload.sessions)
        self.assertIn("20260924", payload.sessions)
        self.assertNotIn("20260925", payload.sessions)
        self.assertIn("20261008", payload.sessions)
        official = [
            item for item in payload.evidence_segments
            if item["evidence_level"] == "exchange-official"
        ]
        self.assertEqual(payload.evidence_level, "mixed")
        self.assertEqual(len(official), 3)
        self.assertTrue(all(item["priority"] == 100 for item in official))


if __name__ == "__main__":
    unittest.main()
