import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "index.html"


class SiteIndexShardDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = SITE.read_text(encoding="utf-8")

    def test_no_fixed_chunk_shard_range(self) -> None:
        self.assertIsNone(re.search(r"chunks-\{000\.\.\d+\}", self.html))
        self.assertIn("chunks-{000..NNN}", self.html)

    def test_no_fixed_posting_shard_range(self) -> None:
        self.assertIsNone(re.search(r"postings-\{00\.\.\d+\}", self.html))
        self.assertIn("postings-{00..NN}", self.html)

    def test_shard_count_is_referenced_from_the_manifest(self) -> None:
        self.assertIn('href="api/search/manifest.json"', self.html)
        self.assertIn("posting_shards", self.html)
        self.assertIn("chunk_count", self.html)
        self.assertIn("chunk_shard_size", self.html)
