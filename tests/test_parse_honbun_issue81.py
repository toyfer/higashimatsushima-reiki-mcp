import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from parse_honbun import parse_honbun

LAW_ID = "r122RG00000093"
SOURCE_URL = "https://example.test/reiki_honbun/r122RG00000093.html"


def toc_chapter(number: str, title: str, articles: str = "") -> str:
    range_span = f'<span class="p cm">{articles}</span>' if articles else ""
    return (
        '<div><div class="eline"><div class="in-chapter"><p class="toc_item-chapter">'
        f'<span class="num cm">{number}</span>\u3000<span class="title cm">{title}</span>{range_span}'
        "</p></div></div></div>\n"
    )


def toc_section(number: str, title: str, articles: str = "") -> str:
    range_span = f'<span class="p cm">{articles}</span>' if articles else ""
    return (
        '<div><div class="eline"><div class="in-chapter"><p class="toc_item-section">'
        f'<span class="num cm">{number}</span>\u3000<span class="title cm">{title}</span>{range_span}'
        "</p></div></div></div>\n"
    )


def body_heading(kind: str, number: str, title: str) -> str:
    return (
        f'<div><div class="eline"><div class="{kind}"><p class="num">'
        f'<span class="num cm">{number}</span>\u3000<span class="title cm">{title}</span>'
        "</p></div></div></div>\n"
    )


def article(label: str, heading: str, body: str) -> str:
    return (
        '<div><div class="eline"><div class="article">'
        f'<p class="title"><span class="cm">{heading}</span></p>'
        f'<p class="num"><span class="num cm">{label}</span>\u3000<span class="clause">'
        f'<span class="p cm">{body}</span></span></p>'
        "</div></div></div>\n"
    )


HTML = (
    '<!DOCTYPE html>\n<html><head><title>東松島市立学校の管理に関する規則</title></head><body>\n'
    '<div id="primary">\n'
    '<div><div class="eline"><div class="toc"><p class="title"><span class="cm">目次</span></p></div></div></div>\n'
    + toc_chapter("第1章", "総則", "(第1条)")
    + toc_chapter("第2章", "小学校及び中学校")
    + toc_section("第1節", "学年、学期及び休業日", "(第2条―第5条)")
    + toc_section("第4節", "学校の組織編成", "(第6条)")
    + '<div><div class="eline"><div class="in-chapter"><p class="toc_item-supplement">'
    '<span class="p cm">附則</span></p></div></div></div>\n'
    + body_heading("chapter", "第1章", "総則")
    + article("第1条", "(目的)", "この規則は、小学校及び中学校の管理運営について定める。")
    + body_heading("chapter", "第2章", "小学校及び中学校")
    + body_heading("section", "第1節", "学年、学期及び休業日")
    + article("第2条", "(学年及び学期)", "学年は、4月1日に始まり、翌年3月31日に終わる。")
    + article("第3条", "(休業日)", "休業日は、次に掲げるとおりとする。")
    + body_heading("section", "第4節", "学校の組織編制")
    + article("第6条", "(組織)", "学校に、校長、教頭及び教諭を置く。")
    + '<div><div class="eline"><p class="p">附則</p></div></div>\n'
    + '<div><div class="eline"><p class="p">この規則は、公布の日から施行する。</p></div></div>\n'
    "<!-- /本文 -->\n</div>\n</body></html>"
)


def parse() -> dict:
    return parse_honbun(HTML, law_id=LAW_ID, source_url=SOURCE_URL)


class TocAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.law = parse()
        cls.by_label = {article["label"]: article for article in cls.law["articles"]}

    def test_table_of_contents_does_not_advance_the_chapter_cursor(self):
        first = self.by_label["第1条"]
        # The TOC repeats 第2章 before 第1条 is parsed; consuming it there put
        # 第1条 under 第2章 (issue #81).
        self.assertEqual(first["chapter"], "第1章")
        self.assertEqual(first["chapter_title"], "総則")
        self.assertEqual(first["section"], "")

    def test_section_carries_its_parent_chapter(self):
        second = self.by_label["第2条"]
        self.assertEqual(second["chapter"], "第2章")
        self.assertEqual(second["chapter_title"], "小学校及び中学校")
        self.assertEqual(second["section"], "第1節")
        self.assertEqual(second["section_title"], "学年、学期及び休業日")

    def test_later_section_keeps_the_same_chapter(self):
        sixth = self.by_label["第6条"]
        self.assertEqual(sixth["chapter"], "第2章")
        self.assertEqual(sixth["section"], "第4節")
        self.assertEqual(sixth["section_title"], "学校の組織編制")

    def test_toc_only_supplement_does_not_create_a_supplement(self):
        self.assertEqual(len(self.law["supplements"]), 1)
        self.assertTrue(self.law["supplements"][0].startswith("附則"))

    def test_no_unstructured_heading_warnings(self):
        self.assertEqual(
            [w for w in self.law["parse_warnings"] if w.startswith("chapter_heading_unstructured")],
            [],
        )

    def test_toc_wording_difference_is_not_reported(self):
        # The TOC says 学校の組織編成 while the body says 学校の組織編制. Only the
        # body spelling may reach the parsed structure.
        titles = [chapter["title"] for chapter in self.law["chapters"]]
        self.assertIn("学校の組織編制", titles)
        self.assertNotIn("学校の組織編成", titles)

    def test_previous_article_bodies_stay_clean(self):
        for article in self.law["articles"]:
            text = article.get("text") or ""
            self.assertNotIn("目次", text)
            self.assertNotIn("第2章", text)


if __name__ == "__main__":
    unittest.main()
