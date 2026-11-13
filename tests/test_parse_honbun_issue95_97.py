import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from parse_honbun import STYLE_SECTION_RE, parse_honbun

FIXTURE = """<html><head><title>東松島市テスト規則</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><div class="head"><p><span>○東松島市テスト規則</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>令和7年4月1日</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>規則第1号</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(基本給)</span></p><p><span>第9条の2</span>　<span>基本給は、この規則の定めるところによる。</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(級別定数)</span></p><p><span>第9条の2の2</span>　<span>級別定数は、別表第2に定めるところによる。</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(削除)</span></p><p><span>第9条の2の3</span>　<span>削除</span></p></div></div></div>
<div><div class="eline"><p><span><span class="word-space">附</span>則</span></p></div></div>
<div><div class="eline"><div class="head"><p><span>(施行期日)</span></p></div></div></div>
<div><div class="eline"><p><span><span>第1条</span>　<span>この規則は、令和7年4月1日から施行する。</span></p></div></div></div>
<div><div class="eline"><p><span><span>第2条</span>　<span>この規則の施行に関し必要な経過措置は、市長が定める。</span></p></div></div></div>
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市テスト規則</h2>
<p class="datenumber-area mt04">令和7年4月1日　規則第1号</p>
<table><tr><td>◆</td><td>令和7年4月1日</td><td>規則第1号</td></tr></table></div>
</body></html>
"""


def parse():
    return parse_honbun(FIXTURE, law_id="r122RG00000999", source_url="https://example.test/999")


class ArticleBranchChainTest(unittest.TestCase):
    """issue #97: 第9条の2の2 のような 2 段以上の枝番を切り詰めない。"""

    def test_two_level_branch_keeps_its_own_label(self) -> None:
        law = parse()
        labels = [article["label"] for article in law["articles"]]
        self.assertEqual(labels, ["第9条の2", "第9条の2の2", "第9条の2の3"])

    def test_labels_do_not_collide(self) -> None:
        labels = [article["label"] for article in parse()["articles"]]
        self.assertEqual(len(labels), len(set(labels)))

    def test_no_branch_fragment_leaks_into_the_first_paragraph(self) -> None:
        for article in parse()["articles"]:
            first = article["paragraphs"][0]["text"] if article["paragraphs"] else ""
            self.assertFalse(first.startswith("の"), article)

    def test_style_section_accepts_two_level_branch(self) -> None:
        self.assertIsNotNone(STYLE_SECTION_RE.match("様式第5号の1の2"))
        self.assertIsNotNone(STYLE_SECTION_RE.match("様式第5号の1"))


class SupplementModeTest(unittest.TestCase):
    """issue #95: 附則内の第N条を本則 articles[] に戻さない。"""

    def test_supplement_articles_stay_out_of_the_body(self) -> None:
        law = parse()
        self.assertEqual([article["label"] for article in law["articles"]], ["第9条の2", "第9条の2の2", "第9条の2の3"])

    def test_supplement_keeps_its_own_articles(self) -> None:
        supplements = parse()["supplements"]
        self.assertEqual(len(supplements), 1)
        self.assertIn("第1条", supplements[0])
        self.assertIn("令和7年4月1日から施行する", supplements[0])
        self.assertIn("第2条", supplements[0])


if __name__ == "__main__":
    unittest.main()
