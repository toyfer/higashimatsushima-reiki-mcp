import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from search_index import SearchIndexBuilder, chunk_law


RESOURCE = {"label": "様式第1号", "href": "https://example.test/sample.rtf", "image_url": "https://example.test/sample.png"}
FORM_RESOURCE = {"label": "様式第1号(第14条関係)", "href": "https://example.test/form1.rtf"}
SECOND_FORM_RESOURCE = {"label": "様式第2号(第15条関係)", "href": "https://example.test/form2.rtf"}
TABLE_RESOURCE = {"label": "別表第3(第9条関係)", "href": "https://example.test/table3.rtf"}


def build_law(resources=None):
    return {
        "id": "r122RG00000070",
        "title": "東松島市事務決裁規程",
        "source_url": "https://example.test/r122RG00000070",
        "articles": [
            {
                "label": "第1条",
                "heading": "(趣旨)",
                "text": "この規程は、事務の決裁に関し必要な事項を定めるものとする。",
            }
        ],
        "appendix_tables": [
            "別表第1 決裁区分\n課長 100万円以下\n部長 500万円以下",
            "(様式第1号) 別に定める",
        ],
        "resources": resources or [],
        "supplements": ["この規程は、公布の日から施行する。"],
    }


class ContentStatusTest(unittest.TestCase):
    def test_chunks_default_to_complete_without_resources(self):
        chunks = chunk_law(build_law())
        self.assertTrue(chunks)
        self.assertTrue(all(chunk["content_status"] == "complete" for chunk in chunks))
        self.assertTrue(all("resource" not in chunk for chunk in chunks))

    def test_external_resource_only_is_decided_per_table(self):
        chunks = chunk_law(build_law([None, RESOURCE]))
        flagged = [chunk for chunk in chunks if chunk["content_status"] == "external_resource_only"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["label"], "(様式第1号) 別に定める")
        self.assertEqual(flagged[0]["resource"]["href"], RESOURCE["href"])
        text_tables = [
            chunk
            for chunk in chunks
            if chunk["kind"] == "appendix_table" and chunk["content_status"] == "complete"
        ]
        self.assertTrue(text_tables)
        self.assertIn("課長 100万円以下", text_tables[0]["text"])

    def test_chunk_shards_carry_content_status_and_resource(self):
        builder = SearchIndexBuilder()
        builder.add_law(build_law([None, RESOURCE]))
        built = builder.build(data_version="test-version", generated_at_utc="2026-11-13T00:00:00Z")
        rows = [row for shard in built["chunks"].values() for row in shard["chunks"]]
        self.assertTrue(rows)
        self.assertTrue(all("content_status" in row for row in rows))
        flagged = [row for row in rows if row["content_status"] == "external_resource_only"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["resource"]["image_url"], RESOURCE["image_url"])
        self.assertEqual(built["manifest"]["external_resource_chunks"], 1)

    def test_resource_index_matches_table_index(self):
        law = build_law([RESOURCE, None])
        law["appendix_tables"] = ["(様式第2号) 別に定める", "別表第1\n課長 100万円以下"]
        chunks = chunk_law(law)
        flagged = [chunk for chunk in chunks if chunk["content_status"] == "external_resource_only"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["label"], "(様式第2号) 別に定める")


    def test_appendix_table_resource_index_beats_positional_alignment(self):
        law = build_law([FORM_RESOURCE, SECOND_FORM_RESOURCE, TABLE_RESOURCE])
        law["appendix_tables"] = [
            "別表第1 決裁区分\n課長 100万円以下",
            "別表第2(第5条関係)",
            "別表第3(第9条関係)",
        ]
        law["appendix_table_resource_index"] = [None, None, 2]
        chunks = chunk_law(law)
        flagged = [chunk for chunk in chunks if chunk["content_status"] == "external_resource_only"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["label"], "別表第3(第9条関係)")
        self.assertEqual(flagged[0]["resource"]["href"], TABLE_RESOURCE["href"])

    def test_legacy_data_without_mapping_falls_back_to_the_label(self):
        law = build_law([FORM_RESOURCE])
        law["appendix_tables"] = ["別表第1 決裁区分\n課長 100万円以下", "様式第1号"]
        chunks = chunk_law(law)
        flagged = [chunk for chunk in chunks if chunk["content_status"] == "external_resource_only"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["resource"]["label"], FORM_RESOURCE["label"])

    def test_mapping_entry_of_none_never_borrows_a_form(self):
        law = build_law([SECOND_FORM_RESOURCE])
        law["appendix_tables"] = ["別表第2(第5条関係)"]
        law["appendix_table_resource_index"] = [None]
        chunks = chunk_law(law)
        self.assertTrue(chunks)
        self.assertTrue(all(chunk["content_status"] == "complete" for chunk in chunks))
        self.assertTrue(all("resource" not in chunk for chunk in chunks))

if __name__ == "__main__":
    unittest.main()
