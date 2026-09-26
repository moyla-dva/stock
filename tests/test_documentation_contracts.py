import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    values = {}
    for line in text[4:end].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


class DocumentationContractsTest(unittest.TestCase):
    def test_current_contracts_have_required_metadata(self):
        for path in sorted((ROOT / "docs" / "current").glob("*.md")):
            if path.name == "README.md":
                continue
            metadata = _frontmatter(path)
            with self.subTest(path=path.name):
                self.assertEqual(metadata.get("status"), "current")
                self.assertTrue(metadata.get("contract_version"))
                self.assertTrue(metadata.get("last_verified"))

    def test_numbered_adrs_and_research_documents_have_metadata(self):
        required_research = {
            "status",
            "strategy_version",
            "data_window",
            "universe",
            "entry_model",
            "data_revision",
            "evidence_level",
            "supersedes",
        }
        for path in sorted((ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")):
            metadata = _frontmatter(path)
            with self.subTest(path=path.name):
                self.assertTrue(metadata.get("status"))
                self.assertTrue(metadata.get("decision_date"))
                self.assertTrue(metadata.get("last_verified"))
        for path in sorted((ROOT / "docs" / "research").glob("*.md")):
            if path.name == "README.md":
                continue
            metadata = _frontmatter(path)
            with self.subTest(path=path.name):
                self.assertEqual(required_research - set(metadata), set())

    def test_repository_markdown_links_resolve(self):
        paths = sorted((ROOT / "docs").rglob("*.md")) + [ROOT / "README.md", ROOT / "AGENT_SYNC.md"]
        failures = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for match in LOCAL_LINK_RE.finditer(text):
                target = match.group(1).strip().split("#", 1)[0].strip("<>")
                if not target or "://" in target or target.startswith(("mailto:", "#")):
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    line = text.count("\n", 0, match.start()) + 1
                    failures.append(f"{path.relative_to(ROOT)}:{line} -> {target}")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
