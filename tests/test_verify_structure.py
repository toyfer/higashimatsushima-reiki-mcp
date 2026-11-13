import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import verify_structure

LAW_ID = "r122RG00000093"

HTML = (
    "<!DOCTYPE html>\n<html><head><title>東松島市立学校の管理に関する規則</title></head><body>\n"
    '<div id="primary">\n'
    '<div><div class="eline"><div class="in-chapter"><p class="toc_item-chapter">'
    '<span class="num cm">第1章</span>\u3000<span class="title cm">総則</span></p></div></div></div>\n'
    '<div><div class="eline"><div class="in-chapter"><p class="toc_item-supplement">'
    '<span class="p cm">附則</span></p></div></div></div>\n'
    '<div><div class="eline"><div class="chapter"><p class="num">'
    '<span class="num cm">第1章</span>\u3000<span class="title cm">総則</span></p></div></div></div>\n'
    '<div><div class="eline"><p class="p">第1条\u3000この規則は、学校の管理運営について定める。</p></div></div>\n'
    '<div><div class="eline"><p class="p">附則</p></div></div>\n'
    '<div><div class="eline"><p class="p">この規則は、公布の日から施行する。</p></div></div>\n'
    "<!-- /本文 -->\n</div>\n</body></html>"
)


def published(**overrides) -> dict:
    data = {
        "article_count": 1,
        "chapters": [{"kind": "chapter", "number": "第1章", "title": "総則", "text": "第1章 総則"}],
        # Builds made before issue #81 counted the TOC 附則 row as a supplement.
        "supplements": ["附則", "附則\nこの規則は、公布の日から施行する。"],
    }
    data.update(overrides)
    return data


class CompareTest(unittest.TestCase):
    def row(self, **overrides):
        return verify_structure.compare(LAW_ID, HTML, published(**overrides), "https://e/test")

    def test_matching_law_reports_no_problems(self):
        self.assertEqual(verify_structure.problems(self.row()), [])

    def test_first_article_keeps_its_chapter(self):
        first = self.row()["first_article"]
        self.assertEqual(first["chapter"], "第1章")
        self.assertEqual(first["section"], "")

    def test_article_count_mismatch_is_reported(self):
        found = verify_structure.problems(self.row(article_count=2))
        self.assertTrue(any("articles 1 != published 2" in problem for problem in found), found)

    def test_chapter_mismatch_is_reported(self):
        found = verify_structure.problems(self.row(chapters=[]))
        self.assertTrue(any("chapters 1 != published 0" in problem for problem in found), found)

    def test_supplement_difference_beyond_the_toc_row_is_reported(self):
        found = verify_structure.problems(self.row(supplements=["附則"] * 7))
        self.assertTrue(any(problem.startswith("supplements") for problem in found), found)

    def test_published_count_equal_to_parsed_is_accepted(self):
        # The published API may show the parsed count (rebuilt) or one more
        # (built before issue #81 counted the table-of-contents 附則 row).
        row = self.row()
        accepted = ["附則"] * row["supplements"]
        self.assertEqual(verify_structure.problems(self.row(supplements=accepted)), [])

    def test_unstructured_heading_warns(self):
        html = HTML.replace(
            '<div><div class="eline"><p class="p">附則</p></div></div>\n',
            '<div><div class="eline"><p class="p">第9章 幻の章</p></div></div>\n',
        )
        row = verify_structure.compare(LAW_ID, html, published(), "https://e/test")
        self.assertTrue(any("unstructured headings" in problem for problem in verify_structure.problems(row)))


if __name__ == "__main__":
    unittest.main()
