import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from parse_honbun import parse_honbun

FIXTURE = """
<html><head><title>東松島市テスト条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><div class="head"><p><span>○東松島市テスト条例</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>令和7年4月1日</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>条例第1号</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(趣旨)</span></p><p><span>第1条</span>　<span>この条例は、テストに関する事項を定めるものとする。</span></p></div></div></div>
<div><div class="eline"><div class="clause"><p><span>2</span>　<span>前項のテストは、次に掲げるものとする。</span></p></div></div></div>
<div><div class="eline"><div class="item"><p><span>(1)</span>　<span>第一のもの</span></p></div></div></div>
<div><div class="eline"><div class="item"><p><span>(2)</span>　<span>第二のもの</span></p></div></div></div>
<div><div class="eline"><p><span><span class="word-space">附</span>則</span></p></div></div>
<div><div class="eline"><div class="clause"><p><span>この条例は、令和7年4月1日から施行する。</span></p></div></div></div>
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市テスト条例</h2>
<p class="datenumber-area mt04">令和7年4月1日　条例第1号</p>
<p class="datenumber-area mt04">(令和7年4月1日施行)</p>
<span class="taikei-item">第1編 <span class="tk-space">総</span>規/第1章 市制施行</span></div>
</div>
<table><tr><td>◆</td><td>令和7年4月1日</td><td>条例第1号</td></tr></table>
</body></html>
"""

UNNUMBERED = """
<html><head><title>東松島市役所の位置を定める条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><p><span>○東松島市役所の位置を定める条例</span></p></div></div>
<div><div class="eline"><p><span>平成17年4月1日</span></p></div></div>
<div><div class="eline"><p><span>条例第1号</span></p></div></div>
<div><div class="eline"><p><span>地方自治法(昭和22年法律第67号)第4条第1項に基づき、東松島市役所の位置を次のとおり定める。</span></p></div></div>
<div><div class="eline"><p><span>東松島市矢本字上河戸36番地1</span></p></div></div>
<div><div class="eline"><p><span>附則</span></p></div></div>
<div><div class="eline"><p><span>この条例は、平成17年4月1日から施行する。</span></p></div></div>
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市役所の位置を定める条例</h2>
<p class="datenumber-area mt04">平成17年4月1日　条例第1号</p>
<span class="taikei-item">第1編 <span class="tk-space">総</span>規/第1章 市制施行</span></div>
</body></html>
"""


PAREN_ITEM = """
<html><head><title>東松島市の休日を定める条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><p><span>○東松島市の休日を定める条例</span></p></div></div>
<div><div class="eline"><p><span>平成17年4月1日</span></p></div></div>
<div><div class="eline"><p><span>条例第2号</span></p></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(市の休日)</span></p><p><span>第1条</span>　<span>次に掲げる日は、市の休日とする。</span></p></div></div></div>
<div><div class="eline"><div class="item"><p><span>(1)</span>　<span>日曜日及び土曜日</span></p></div></div></div>
<div><div class="eline"><div class="item"><p><span>(2)</span>　<span>国民の祝日に関する法律(昭和23年法律第178号)に規定する休日</span></p></div></div></div>
<div><div class="eline"><div class="item"><p><span>(3)</span>　<span>12月29日から翌年の1月3日までの日(前号に掲げる日を除く。)</span></p></div></div></div>
<div><div class="eline"><div class="clause"><p><span>2</span>　<span>前項の規定は、妨げるものではない。</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(期限の特例)</span></p><p><span>第2条</span>　<span>期限の特例を定める。</span></p></div></div></div>
<div><div class="eline"><p><span><span class="word-space">附</span>則</span></p></div></div>
<div><div class="eline"><div class="clause"><p><span>この条例は、平成17年4月1日から施行する。</span></p></div></div></div>
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市の休日を定める条例</h2>
<p class="datenumber-area mt04">平成17年4月1日　条例第2号</p>
<span class="taikei-item">第1編 総規/第1章 市制施行</span></div>
</body></html>
"""

PAREN_ITEM_FULLWIDTH = PAREN_ITEM.replace("(市の休日)", "（市の休日）").replace("(3)", "（3）").replace("(前号に掲げる日を除く。)", "（前号に掲げる日を除く。）").replace("(期限の特例)", "（期限の特例）")


class ParseHonbunTest(unittest.TestCase):
    def test_numbered_ordinance(self) -> None:
        data = parse_honbun(FIXTURE, law_id="r122RG99999999", source_url="https://example.invalid/x.html")
        self.assertEqual(data["title"], "東松島市テスト条例")
        self.assertEqual(data["enacted_date"], "令和7年4月1日")
        self.assertEqual(data["ordinance_number"], "条例第1号")
        self.assertEqual(data["classification"], "第1編 総規/第1章 市制施行")
        self.assertEqual(data["article_count"], 1)
        article = data["articles"][0]
        self.assertEqual(article["label"], "第1条")
        self.assertEqual(article["heading"], "(趣旨)")
        self.assertEqual(len(article["paragraphs"][1]["items"]), 2)
        self.assertEqual(len(data["supplements"]), 1)

    def test_item_ending_with_parenthetical_is_not_heading(self) -> None:
        data = parse_honbun(PAREN_ITEM, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        article = data["articles"][0]
        self.assertEqual(article["heading"], "(市の休日)")
        items = article["paragraphs"][0]["items"]
        self.assertEqual([item["label"] for item in items], ["(1)", "(2)", "(3)"])
        self.assertEqual(items[2]["text"], "12月29日から翌年の1月3日までの日(前号に掲げる日を除く。)")
        self.assertIn("(3) 12月29日から翌年の1月3日までの日(前号に掲げる日を除く。)", article["text"])
        self.assertEqual(data["articles"][1]["heading"], "(期限の特例)")
        self.assertEqual(data["parse_warnings"], [])

    def test_fullwidth_item_ending_with_parenthetical_is_not_heading(self) -> None:
        data = parse_honbun(PAREN_ITEM_FULLWIDTH, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        article = data["articles"][0]
        items = article["paragraphs"][0]["items"]
        self.assertEqual([item["label"] for item in items], ["(1)", "(2)", "(3)"])
        self.assertTrue(items[2]["text"].endswith("（前号に掲げる日を除く。）"))
        self.assertEqual(data["parse_warnings"], [])

    def test_unnumbered_ordinance(self) -> None:
        data = parse_honbun(UNNUMBERED, law_id="r122RG00000001", source_url="https://example.invalid/1.html")
        self.assertEqual(data["article_count"], 0)
        self.assertIn("上河戸36番地1", data["body_text"])
        self.assertEqual(data["parse_warnings"], [])


if __name__ == "__main__":
    unittest.main()
