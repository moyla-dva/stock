import unittest

from stock_analyzer.code_utils import code_from_cache_filename, normalize_code


class CodeUtilsTest(unittest.TestCase):
    def test_normalize_code_accepts_supported_market_formats(self):
        accepted = {
            "600063": "600063",
            "sh600063": "600063",
            "SZ000001": "000001",
            "bj920001": "920001",
            "600063.SH": "600063",
            "000001.sz": "000001",
            " 920001.BJ ": "920001",
        }
        for raw, expected in accepted.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_code(raw), expected)

    def test_normalize_code_rejects_embedded_or_oversized_digits(self):
        for raw in ("xx600063yy", "12345678", "600063_20260924.json", "1.600063", "abc"):
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_code(raw))

    def test_cache_filename_extraction_requires_six_digit_prefix_and_separator(self):
        self.assertEqual(code_from_cache_filename("600063_20250429_20260924.json"), "600063")
        self.assertEqual(code_from_cache_filename("300829_20250429_qfq.csv"), "300829")
        self.assertIsNone(code_from_cache_filename("xx600063_20260924.json"))
        self.assertIsNone(code_from_cache_filename("12345678_20260924.json"))


if __name__ == "__main__":
    unittest.main()
