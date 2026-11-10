import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import search_index
from search_index import build_search_index, chunk_law, text_bigrams


def law(**kw):
    base = {"id": "r122RG00000001", "title": "テスト条例", "source_url": "https://example.invalid/1.html", "articles": [], "appendix_tables": [], "supplements": [], "preamble": [], "body_text": ""}
    base.update(kw)
    return base


class ChunkLawTest(unittest.TestCase):
    def test_body_only_law_becomes_a_preamble_chunk(self):
        chunks = chunk_law(law(body_text="建設工事の契約の取扱いを定める。"))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["label"], "前文")
        self.assertEqual(chunks[0]["kind"], "preamble")
        self.assertIn("契約", chunks[0]["search_text"])

    def test_preamble_list_is_used_when_body_text_is_empty(self):
        chunks = chunk_law(law(preamble=["この訓令は契約の方法を定める。"]))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["label"], "前文")

    def test_preamble_and_articles_coexist(self):
        chunks = chunk_law(law(preamble=["この条例は、契約事務の適正化を目的として必要な事項を定める前文である。"], articles=[{"label": "第1条", "heading": "(趣旨)", "text": "第1条 本文。", "paragraphs": []}]))
        labels = [c["label"] for c in chunks]
        self.assertIn("前文", labels)
        self.assertIn("第1条", labels)

    def test_long_article_is_split_by_paragraph(self):
        long_a = "予定価格の決定に関する説明。" * 60
        long_b = "契約締結の手続に関する説明。" * 60
        chunks = chunk_law(law(articles=[{"label": "第2条", "heading": "(契約)", "text": "", "paragraphs": [{"number": 1, "text": long_a, "items": []}, {"number": 2, "text": long_b, "items": []}]}]))
        self.assertEqual(len(chunks), 2)
        self.assertEqual([c["label"] for c in chunks], ["第2条 第1項", "第2条 第2項"])
        self.assertTrue(all(c["kind"] == "article_paragraph" for c in chunks))

    def test_appendix_label_uses_first_raw_line(self):
        chunks = chunk_law(law(appendix_tables=["別表第1（第3条関係）\n業種区分 金額\n測量業務 100万円\n土木業務 200万円"]))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["label"], "別表第1（第3条関係）")
        self.assertNotIn("業種区分", chunks[0]["label"])
        self.assertIn("測量業務", chunks[0]["search_text"])

    def test_supplements_are_chunks(self):
        chunks = chunk_law(law(supplements=["附則\nこの条例は公布の日から施行する。"]))
        self.assertEqual(chunks[0]["label"], "附則")
        self.assertEqual(chunks[0]["kind"], "supplement")

    def test_chunk_carries_source_url(self):
        chunks = chunk_law(law(body_text="本文。"))
        self.assertEqual(chunks[0]["source_url"], "https://example.invalid/1.html")


class PostingBuildTest(unittest.TestCase):
    def test_many_articles_in_one_law_do_not_fill_a_posting(self):
        laws = []
        for n in range(12):
            laws.append(law(id=f"r122RG000001{n:02d}", title="多数条条例", articles=[{"label": f"第{i}条", "heading": "", "text": f"第{i}条 監査について定める。", "paragraphs": []} for i in range(1, 8)]))
        # Unrelated chunks keep the shared term from being an artefact of a
        # tiny corpus, the way the full corpus dilutes common terms.
        for n in range(30):
            laws.append(law(id=f"r122RG000002{n:02d}", title="無関係条例", articles=[{"label": "第1条", "heading": "", "text": "第1条 手数料の額を定める。", "paragraphs": []}]))
        laws.append(law(id="r122RG00000999", title="関連条例", articles=[{"label": "第1条", "heading": "", "text": "第1条 監査について定める。", "paragraphs": []}]))
        built = build_search_index(laws).build(data_version="v1", generated_at_utc="t")
        posting_files = list(built["postings"].values())
        hits = []
        for f in posting_files:
            if "監査" in f["terms"]:
                hits = f["terms"]["監査"]
        self.assertTrue(hits)
        chunk_by_index = {}
        for cf in built["chunks"].values():
            for row in cf["chunks"]:
                chunk_by_index[row["i"]] = row
        law_ids = [chunk_by_index[i]["law_id"] for i, _ in hits]
        self.assertIn("r122RG00000999", law_ids)
        from collections import Counter
        self.assertLessEqual(max(Counter(law_ids).values()), 3)

    def test_short_rule_beats_repetitive_table_for_amount_query(self):
        # A salary-style table repeats digit bigrams hundreds of times. For a
        # practical query the short chunk stating the threshold rule must win
        # once length normalization is applied, and the table must stay in the
        # postings (normalized, not dropped).
        table_body = " ".join(f"{n * 100}円" for n in range(1, 400))
        laws = [
            law(id="r122RG00000011", title="給料表条例", appendix_tables=[f"別表第1\n{table_body}"]),
            law(id="r122RG00000012", title="決裁規程", articles=[{"label": "別表第1", "heading": "", "text": "契約金額が600万円以下の場合は部長が決裁する。", "paragraphs": []}]),
        ]
        built = build_search_index(laws).build(data_version="v1", generated_at_utc="t")
        chunk_by_index = {}
        for cf in built["chunks"].values():
            for row in cf["chunks"]:
                chunk_by_index[row["i"]] = row
        from search_index import text_bigrams
        grams = set(text_bigrams("契約 600万円 決裁"))
        scores = {}
        seen_indexes = set()
        for f in built["postings"].values():
            for gram in grams:
                for index, score in (f["terms"].get(gram) or []):
                    scores[index] = scores.get(index, 0) + score
                    seen_indexes.add(index)
        ranked = sorted(scores, key=lambda i: (-scores[i], i))
        self.assertTrue(ranked)
        self.assertEqual(chunk_by_index[ranked[0]]["law_id"], "r122RG00000012")
        table_indexes = [i for i, row in chunk_by_index.items() if row["law_id"] == "r122RG00000011"]
        self.assertTrue(any(i in seen_indexes for i in table_indexes))

    def test_chunk_rows_carry_full_text_for_request_time_verification(self):
        body = "随意契約は600万円以下の額で締結できる。" * 20
        built = build_search_index([law(id="r122RG00000032", title="委託規程", articles=[{"label": "第3条", "heading": "", "text": body, "paragraphs": []}])]).build(data_version="v1", generated_at_utc="t")
        rows = [row for cf in built["chunks"].values() for row in cf["chunks"]]
        self.assertTrue(rows)
        self.assertIn("text", rows[0])
        self.assertEqual(rows[0]["text"], body.strip())
        self.assertLessEqual(len(rows[0]["snippet"]), search_index.SNIPPET_CHARS)

    def test_manifest_records_scoring_parameters(self):
        built = build_search_index([law(body_text="本文検索の対象。")]).build(data_version="v1", generated_at_utc="t")
        manifest = built["manifest"]
        self.assertEqual(manifest["chunk_shard_size"], search_index.CHUNK_SHARD_SIZE)
        self.assertEqual(manifest["length_norm_alpha"], search_index.LENGTH_NORM_ALPHA)
        self.assertEqual(manifest["appendix_boost"], search_index.APPENDIX_BOOST)
        self.assertEqual(search_index.CHUNK_SHARD_SIZE, 500)

    def test_manifest_is_keyword_only(self):
        built = build_search_index([law(body_text="本文検索の対象。")]).build(data_version="v1", generated_at_utc="t")
        manifest = built["manifest"]
        self.assertEqual(manifest["kind"], "bigram-tfidf")
        for cf in built["chunks"].values():
            for row in cf["chunks"]:
                self.assertNotIn("v", row)
                self.assertIn("source_url", row)

    def test_write_emits_manifest_chunks_and_postings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "search"
            manifest = build_search_index([law(body_text="本文検索の対象。")]).write(root, data_version="v9", generated_at_utc="t")
            self.assertEqual(manifest["data_version"], "v9")
            self.assertTrue((root / "manifest.json").exists())
            written = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(written["chunk_count"], manifest["chunk_count"])
            for name in manifest["files"]["chunks"] + manifest["files"]["postings"]:
                self.assertTrue((root / name).exists(), name)

    def test_bigrams_normalize_fullwidth_digits(self):
        grams = text_bigrams("６００万円")
        self.assertIn("60", grams)


if __name__ == "__main__":
    unittest.main()
