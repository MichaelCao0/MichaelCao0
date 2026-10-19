import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("research", ROOT / ".github/scripts/update_research.py")
research = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research)


class ScholarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "tests/fixtures/scholar.html").read_text()
        cls.catalog = json.loads((ROOT / "research/publications.json").read_text())

    def test_real_profile_counts_and_zero_citation_paper(self):
        snapshot = research.parse_scholar(self.html, self.catalog)
        self.assertEqual((snapshot["citations"], snapshot["h_index"], snapshot["i10_index"]), (203, 6, 6))
        self.assertEqual(len(snapshot["papers"]), 9)
        self.assertEqual(snapshot["papers"]["2osOgNQ5qMEC"]["citations"], 64)
        self.assertEqual(snapshot["papers"]["Se3iqnhoufwC"]["citations"], 0)
        self.assertIn("cites=14608674073757441090", snapshot["papers"]["2osOgNQ5qMEC"]["cited_by_url"])

    def test_blocked_and_wrong_identity_are_rejected(self):
        for source in ("<h1>Sorry, unusual traffic</h1>", self.html.replace("Zhe Cao</div>", "Someone Else</div>")):
            with self.subTest(source=source[:40]), self.assertRaises(ValueError):
                research.parse_scholar(source, self.catalog)

    def test_partial_profile_is_rejected(self):
        source = self.html.replace("Se3iqnhoufwC", "missing-paper")
        with self.assertRaisesRegex(ValueError, "partial list"):
            research.parse_scholar(source, self.catalog)

    def test_invalid_count_is_not_silently_zeroed(self):
        source = self.html.replace(">64</a>", ">unavailable</a>")
        self.assertNotEqual(source, self.html)
        with self.assertRaises(ValueError):
            research.parse_scholar(source, self.catalog)

    def test_only_research_block_is_updated(self):
        before, after = "existing intro\n", "\nexisting activity"
        text = before + research.START + "old" + research.END + after
        self.assertEqual(research.update_readme(text, "new"), before + research.START + "\nnew\n" + research.END + after)
        with self.assertRaises(ValueError):
            research.update_readme(text + research.START, "new")

    def test_http_failure_preserves_successful_snapshot_and_date(self):
        snapshot = research.parse_scholar(self.html, self.catalog)
        snapshot["updated_utc"] = "2026-10-18"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "research").mkdir()
            (root / "research/publications.json").write_text(json.dumps(self.catalog))
            cache = root / "research/scholar.json"
            cache.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
            readme = root / "README.md"
            readme.write_text(research.START + "\n" + research.render(self.catalog, snapshot) + "\n" + research.END)
            old_cache, old_readme = cache.read_bytes(), readme.read_bytes()
            blocked = HTTPError("https://scholar.google.com", 429, "rate limited", {}, None)
            with patch.object(research, "ROOT", root), patch.object(research, "urlopen", side_effect=blocked), patch("sys.argv", ["update_research.py"]):
                research.main()
            self.assertEqual(cache.read_bytes(), old_cache)
            self.assertEqual(readme.read_bytes(), old_readme)


if __name__ == "__main__":
    unittest.main()
