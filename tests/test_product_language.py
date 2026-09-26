import json
import unittest
from pathlib import Path

from stock_analyzer.c_signal_v2_contracts import V2_SIGNAL_CONTRACTS
from stock_analyzer.events import SIGNAL_DEFINITIONS
from stock_analyzer.scan_explainer import build_scan_explanation


ROOT = Path(__file__).resolve().parents[1]
DISALLOWED_UI_TERMS = ("回测", "胜率", "空仓", "持仓", "减仓", "卖出")


class ProductLanguageTest(unittest.TestCase):
    def test_frontend_uses_research_tool_language(self):
        paths = [ROOT / "templates" / "index.html"]
        paths.extend(sorted((ROOT / "static" / "js").glob("*.js")))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for term in DISALLOWED_UI_TERMS:
                with self.subTest(path=path.name, term=term):
                    self.assertNotIn(term, text)

    def test_public_signal_labels_use_conditional_language(self):
        explanation = build_scan_explanation({
            "signal_name": "结构候选",
            "reason": "结构确认",
            "win_rate": 60.0,
            "avg_ret": 2.0,
        })
        text = json.dumps(
            {
                "contracts": V2_SIGNAL_CONTRACTS,
                "definitions": SIGNAL_DEFINITIONS,
                "explanation": explanation,
            },
            ensure_ascii=False,
        )
        for term in DISALLOWED_UI_TERMS:
            with self.subTest(term=term):
                self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
