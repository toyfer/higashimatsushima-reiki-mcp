import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from parse_honbun import is_amendment_note, parse_honbun


LAW_ID = "r122RG00001013"
SOURCE_URL = "https://example.test/reiki_honbun/r122RG00001013.html"


def page(body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html><head><title>東松島市災害対策本部運営要綱</title></head>\n<body>\n"
        '<div id="primary">\n'
        f"{body}\n"
        "<!-- /本文 -->\n</div>\n</body></html>"
    )


HTML_AMENDMENT = page(
    '<div class="chapter"><p class="num"><span>第2章</span> <span>本部</span></p></div>\n'
    "<p>第10条 本章は、災害対策本部の設置について定める。</p>\n"
    "<p>第11条 本部長は、本部の事務を総括する。</p>\n"
    "<p>(令8訓令甲23・一部改正)</p>\n"
    '<div class="chapter"><p class="num"><span>第3章</span> <span>非常配備態勢</span></p></div>\n'
    "<p>第12条 副本部長は、本部長を補佐する。</p>"
)

HTML_MIXED = page(
    "<p>第3条 別表に掲げる基準による。</p>\n"
    "<p>別表第1(第3条関係) 被害認定基準</p>\n"
    "<p>1 全壊 50パーセント以上</p>\n"
    '<div class="form_section"><p class="num"><a href="#" onClick="fileDownloadAction2(\'honbun_1.rtf\')">'
    "<span>様式第1号</span><span>(第14条関係)</span></a></p></div>\n"
    '<div class="form_section"><p class="num"><a href="#" onClick="fileDownloadAction2(\'honbun_2.rtf\')">'
    "<span>別表第2</span><span>(第5条関係)</span></a></p></div>\n"
    '<div id="e1" class="xref_frame cm"><p><img src="/reiki/honbun_1.png"></p></div>\n'
    '<div id="e2" class="xref_frame cm"><p><img src="/reiki/honbun_2.png"></p></div>'
)

HTML_HEADING = page("<p>(目的)</p>\n<p>第1条 この要綱は、本部の運営について定める。</p>")


def parse(html: str) -> dict:
    return parse_honbun(html, law_id=LAW_ID, source_url=SOURCE_URL)


class AmendmentNoteTest(unittest.TestCase):
    def test_amendment_notes_are_recognised(self):
        self.assertTrue(is_amendment_note("(令8訓令甲23・一部改正)"))
        self.assertTrue(is_amendment_note("（平成30条例第12号）"))
        self.assertTrue(is_amendment_note("(令5訓令甲3・全部改正)"))
        self.assertFalse(is_amendment_note("(目的)"))
        self.assertFalse(is_amendment_note("(貸付条件)"))
        self.assertFalse(is_amendment_note("第12条の2))"))

    def test_amendment_note_does_not_become_the_next_heading(self):
        law = parse(HTML_AMENDMENT)
        labels = [article["label"] for article in law["articles"]]
        self.assertEqual(labels, ["第10条", "第11条", "第12条"])
        by_label = {article["label"]: article for article in law["articles"]}
        self.assertEqual(by_label["第12条"]["heading"], "")
        self.assertEqual(by_label["第10条"]["heading"], "")

    def test_amendment_note_stays_in_the_amended_article_text(self):
        law = parse(HTML_AMENDMENT)
        by_label = {article["label"]: article for article in law["articles"]}
        self.assertIn("一部改正", by_label["第11条"]["text"])
        self.assertNotIn("一部改正", by_label["第12条"]["text"])

    def test_chapter_after_the_note_is_assigned_to_the_next_article(self):
        law = parse(HTML_AMENDMENT)
        by_label = {article["label"]: article for article in law["articles"]}
        self.assertEqual(by_label["第10条"]["chapter"], "第2章")
        self.assertEqual(by_label["第12条"]["chapter"], "第3章")
        self.assertEqual(by_label["第12条"]["chapter_title"], "非常配備態勢")

    def test_ordinary_heading_still_applies(self):
        law = parse(HTML_HEADING)
        self.assertEqual(law["articles"][0]["heading"], "(目的)")


class StyleAndResourceTest(unittest.TestCase):
    def test_style_sections_are_not_glued_to_the_last_table(self):
        law = parse(HTML_MIXED)
        self.assertTrue(law["appendix_tables"])
        self.assertNotIn("様式第1号", law["appendix_tables"][0])
        self.assertTrue(law["appendix_styles"])
        self.assertTrue(law["appendix_styles"][0].startswith("様式第1号"))

    def test_resources_carry_identity(self):
        law = parse(HTML_MIXED)
        self.assertEqual(len(law["resources"]), 2)
        form, table = law["resources"]
        self.assertEqual(form["kind"], "form")
        self.assertIsNone(form["table_number"])
        self.assertEqual(form["seq"], 1)
        self.assertEqual(table["kind"], "appendix")
        self.assertEqual(table["table_number"], 2)
        self.assertEqual(table["image_url"], "/reiki/honbun_2.png")

    def test_appendix_table_resource_index_ignores_positional_assumptions(self):
        law = parse(HTML_MIXED)
        mapping = law["appendix_table_resource_index"]
        self.assertEqual(len(mapping), len(law["appendix_tables"]))
        self.assertEqual(mapping, [None, 1])
        mapping_len_ok = max((index for index in mapping if index is not None), default=-1) < len(law["resources"])
        self.assertTrue(mapping_len_ok)

    def test_style_does_not_disturb_table_order(self):
        law = parse(HTML_MIXED)
        self.assertEqual(len(law["appendix_tables"]), 2)
        self.assertTrue(law["appendix_tables"][0].startswith("別表第1"))
        self.assertTrue(law["appendix_tables"][1].startswith("別表第2"))


if __name__ == "__main__":
    unittest.main()
