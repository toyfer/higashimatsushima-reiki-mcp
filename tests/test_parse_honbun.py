import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from parse_honbun import (
    STYLE_SECTION_RE,
    appendix_table_key,
    build_resource_map,
    is_amendment_note,
    parse_honbun,
)

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

NESTED_HEADING = PAREN_ITEM.replace("(期限の特例)", "(職員（非常勤）の勤務)")
NESTED_HEADING_MIXED = PAREN_ITEM.replace("(期限の特例)", "（職員(非常勤)の勤務）")


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

    def test_nested_parentheses_heading_is_preserved(self) -> None:
        data = parse_honbun(NESTED_HEADING, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        self.assertEqual(data["articles"][1]["heading"], "(職員（非常勤）の勤務)")
        self.assertEqual(data["parse_warnings"], [])

    def test_mixed_parentheses_heading_is_preserved(self) -> None:
        data = parse_honbun(NESTED_HEADING_MIXED, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        self.assertEqual(data["articles"][1]["heading"], "（職員(非常勤)の勤務）")
        self.assertEqual(data["parse_warnings"], [])

    def test_unnumbered_ordinance(self) -> None:
        data = parse_honbun(UNNUMBERED, law_id="r122RG00000001", source_url="https://example.invalid/1.html")
        self.assertEqual(data["article_count"], 0)
        self.assertIn("上河戸36番地1", data["body_text"])
        self.assertEqual(data["parse_warnings"], [])

INLINE_HEADING = PAREN_ITEM.replace(
    "<p><span>第2条</span>　<span>期限の特例を定める。</span></p>",
    "<p><span>第2条</span>　<span>（職員(非常勤)の勤務）職員の勤務条件は、別に定める。</span></p>",
)
INLINE_HEADING_REVERSED = PAREN_ITEM.replace(
    "<p><span>第2条</span>　<span>期限の特例を定める。</span></p>",
    "<p><span>第2条</span>　<span>(職員（非常勤）の勤務)職員の勤務条件は、別に定める。</span></p>",
)
# Outer pair mixes widths: legacy input the old depth-blind splitter accepted.
INLINE_HEADING_OUTER_MIXED = PAREN_ITEM.replace(
    "<p><span>第2条</span>　<span>期限の特例を定める。</span></p>",
    "<p><span>第2条</span>　<span>(見出し）見出しに続く本文である。</span></p>",
)
INLINE_HEADING_OUTER_MIXED_REVERSED = PAREN_ITEM.replace(
    "<p><span>第2条</span>　<span>期限の特例を定める。</span></p>",
    "<p><span>第2条</span>　<span>（見出し)見出しに続く本文である。</span></p>",
)
# The inner pair is width-mismatched while the outer pair is full-width.
INLINE_HEADING_INNER_MIXED = PAREN_ITEM.replace(
    "<p><span>第2条</span>　<span>期限の特例を定める。</span></p>",
    "<p><span>第2条</span>　<span>（職員(非常勤）の勤務）職員の勤務条件は、別に定める。</span></p>",
)

BRANCHED = """
<html><head><title>東松島市枝番検証条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><div class="head"><p><span>○東松島市枝番検証条例</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>令和7年4月1日</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>条例第99号</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>（趣旨）</span></p><p><span>第1条</span>　<span>この条例は検証用である。</span></p></div></div></div>
<div><div class="eline"><div class="article"><p><span>第2条の2</span>　<span>枝番の本文である。</span></p></div></div></div>
<div><div class="eline"><div class="article"><p><span>第３条</span>　<span>全角条番号の本文である。</span></p></div></div></div>
<div><div class="eline"><div class="clause"><p><span>２</span>　<span>全角項番号の本文である。</span></p></div></div></div>
<div><div class="eline"><div class="item"><p><span>（１）</span>　<span>全角の号である。</span></p></div></div></div>
<div><div class="eline"><p><span>別表第1</span></p></div></div>
<div><div class="eline"><p><span>別表の内容である。</span></p></div></div>
<div><div class="eline"><p><span><span class="word-space">附</span>則</span></p></div></div>
<div><div class="eline"><div class="clause"><p><span>この条例は、令和7年4月1日から施行する。</span></p></div></div></div>
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市枝番検証条例</h2>
<p class="datenumber-area mt04">令和7年4月1日　条例第99号</p>
<span class="taikei-item">第1編 総規/第1章 市制施行</span></div>
</div>
<div id="shoshi-inf" class="tab-body"><div class="shoshi">
<div><span class="enkaku-title">沿革情報</span></div>
<table><tr><td class="seitei-icon">◆</td><td>令和7年4月1日</td><td>条例第99号</td></tr></table>
</div></div><!-- /書誌情報 -->
</body></html>
"""

# The next article's heading must not be appended to the previous article (#40).
NEXT_HEADING = """
<html><head><title>東松島市休日検証条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><p><span>（市の休日）</span></p></div></div>
<div><div class="eline"><p><span>第1条</span>　<span>市の休日を定める。</span></p></div></div>
<div><div class="eline"><p><span>（期限の特例）</span></p></div></div>
<div><div class="eline"><p><span>第2条</span>　<span>期限の特例を定める。</span></p></div></div>
</div></div></div><!-- /本文 -->
<div id="shoshi-inf" class="tab-body"><div class="shoshi">
<div><span class="enkaku-title">沿革情報</span></div>
<table><tr><td class="seitei-icon">◆</td><td>平成17年4月1日</td><td>条例第2号</td></tr></table>
</div></div><!-- /書誌情報 -->
</body></html>
"""

# 別表(第2条関係) must be an appendix table, not part of the last supplement (#38).
RELATION_APPENDIX = """
<html><head><title>東松島市別表検証条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><p><span>（趣旨）</span></p></div></div>
<div><div class="eline"><p><span>第1条</span>　<span>手数料を徴収する。</span></p></div></div>
<div><div class="eline"><p><span><span class="word-space">附</span>則</span></p></div></div>
<div><div class="eline"><p><span>この条例は、公布の日から施行する。</span></p></div></div>
<div><div class="eline"><div class="num"><p><span>別表</span><span>(第2条関係)</span></p></div></div></div>
<div><div class="eline"><p><span>事務 名称 金額</span></p></div></div>
<div><div class="eline"><p><span>納税証明 手数料 300円</span></p></div></div>
</div></div></div><!-- /本文 -->
<div id="shoshi-inf" class="tab-body"><div class="shoshi">
<div><span class="enkaku-title">沿革情報</span></div>
<table>
<tr><td class="seitei-icon">◆</td><td>平成17年4月1日</td><td>条例第51号</td></tr>
<tr><td class="seitei-icon">◇</td><td>令和6年3月1日</td><td>条例第6号</td></tr>
</table>
</div></div><!-- /書誌情報 -->
</body></html>
"""

# Appendix rows shaped like history rows must never reach history (#36).
HISTORY_TABLE_WITH_APPENDIX_SHAPE = """
<html><head><title>東松島市沿革検証条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><p><span>第1条</span>　<span>本文である。</span></p></div></div>
<div><div class="eline"><p><span>別表第1</span></p></div></div>
<div><div class="eline"><p><span>1 手数料の名称</span></p></div></div>
</div></div></div><!-- /本文 -->
<div id="shoshi-inf" class="tab-body"><div class="shoshi">
<div><span class="enkaku-title">沿革情報</span></div>
<table><tr><td class="seitei-icon">◆</td><td>平成17年4月1日</td><td>条例第51号</td></tr></table>
<table><tr><td>1</td><td>手数料の名称</td></tr><tr><td>2</td><td>金額</td></tr></table>
</div></div><!-- /書誌情報 -->
</body></html>
"""


# Article whose item lines appear before any structured paragraph exists, so the
# text/structured item counts diverge and the blocking warning must fire (#21).
ITEM_MISMATCH = """
<html><head><title>東松島市号検証条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><div class="head"><p><span>○東松島市号検証条例</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>令和7年4月1日</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>条例第99号</span></p></div></div></div>
<div><div class="eline"><div class="article"><p><span>第1条</span></p><p><span>（１）　一つ目の号である。</span></p></div></div></div>
<div><div class="eline"><div class="item"><p><span>（２）</span>　<span>二つ目の号である。</span></p></div></div></div>
<div><div class="eline"><p><span><span class="word-space">附</span>則</span></p></div></div>
<div><div class="eline"><div class="clause"><p><span>この条例は、令和7年4月1日から施行する。</span></p></div></div></div>
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市号検証条例</h2>
<p class="datenumber-area mt04">令和7年4月1日　条例第99号</p>
<span class="taikei-item">第1編 総規/第1章 市制施行</span></div>
</body></html>
"""

EMPTY_BODY = """
<html><head><title>東松島市空条例</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市空条例</h2>
<p class="datenumber-area mt04">令和7年4月1日　条例第99号</p>
<span class="taikei-item">第1編 総規/第1章 市制施行</span></div>
</body></html>
"""


class InlineHeadingTest(unittest.TestCase):
    def test_inline_mixed_parentheses_heading_is_preserved(self) -> None:
        data = parse_honbun(INLINE_HEADING, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        article = data["articles"][1]
        self.assertEqual(article["heading"], "（職員(非常勤)の勤務）")
        self.assertEqual(article["paragraphs"][0]["text"], "職員の勤務条件は、別に定める。")
        self.assertEqual(data["parse_warnings"], [])

    def test_inline_reversed_mixed_parentheses_heading_is_preserved(self) -> None:
        data = parse_honbun(INLINE_HEADING_REVERSED, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        article = data["articles"][1]
        self.assertEqual(article["heading"], "(職員（非常勤）の勤務)")
        self.assertEqual(article["paragraphs"][0]["text"], "職員の勤務条件は、別に定める。")
        self.assertEqual(data["parse_warnings"], [])

    def test_inline_outer_mixed_parentheses_heading_is_preserved(self) -> None:
        data = parse_honbun(INLINE_HEADING_OUTER_MIXED, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        article = data["articles"][1]
        self.assertEqual(article["heading"], "(見出し）")
        self.assertEqual(article["paragraphs"][0]["text"], "見出しに続く本文である。")
        self.assertEqual(data["parse_warnings"], [])

    def test_inline_outer_mixed_parentheses_heading_reversed_is_preserved(self) -> None:
        data = parse_honbun(INLINE_HEADING_OUTER_MIXED_REVERSED, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        article = data["articles"][1]
        self.assertEqual(article["heading"], "（見出し)")
        self.assertEqual(article["paragraphs"][0]["text"], "見出しに続く本文である。")
        self.assertEqual(data["parse_warnings"], [])

    def test_inline_inner_mixed_parentheses_heading_is_preserved(self) -> None:
        data = parse_honbun(INLINE_HEADING_INNER_MIXED, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        article = data["articles"][1]
        self.assertEqual(article["heading"], "（職員(非常勤）の勤務）")
        self.assertEqual(article["paragraphs"][0]["text"], "職員の勤務条件は、別に定める。")
        self.assertEqual(data["parse_warnings"], [])


class ParseWarningTest(unittest.TestCase):
    def test_item_structure_mismatch_is_reported(self) -> None:
        data = parse_honbun(ITEM_MISMATCH, law_id="r122RG00000002", source_url="https://example.invalid/mismatch.html")
        self.assertTrue(
            any(w.startswith("item_structure_mismatch:第1条:") for w in data["parse_warnings"]),
            data["parse_warnings"],
        )

    def test_no_articles_parsed_is_reported(self) -> None:
        data = parse_honbun(EMPTY_BODY, law_id="r122RG00000002", source_url="https://example.invalid/empty.html")
        self.assertEqual(data["article_count"], 0)
        self.assertIn("no_articles_parsed", data["parse_warnings"])

    def test_branch_fullwidth_appendix_and_history(self) -> None:
        data = parse_honbun(BRANCHED, law_id="r122RG00000002", source_url="https://example.invalid/branch.html")
        self.assertEqual([a["label"] for a in data["articles"]], ["第1条", "第2条の2", "第3条"])
        self.assertEqual(data["articles"][1]["number"], 2)
        self.assertEqual(data["articles"][1]["branch"], 2)
        third = data["articles"][2]
        self.assertEqual(third["paragraphs"][1]["number"], 2)
        self.assertEqual(third["paragraphs"][1]["items"], [{"label": "(1)", "text": "全角の号である。"}])
        self.assertEqual(len(data["appendix_tables"]), 1)
        self.assertIn("別表第1", data["appendix_tables"][0])
        self.assertEqual(data["history"], [{"date": "令和7年4月1日", "number": "条例第99号"}])
        self.assertEqual(data["parse_warnings"], [])



class TextIntegrityTest(unittest.TestCase):
    def test_next_article_heading_is_not_appended_to_previous_text(self) -> None:
        data = parse_honbun(NEXT_HEADING, law_id="r122RG00000002", source_url="https://example.invalid/next.html")
        first, second = data["articles"][0], data["articles"][1]
        self.assertEqual(first["heading"], "（市の休日）")
        self.assertNotIn("期限の特例", first["text"])
        self.assertEqual(second["heading"], "（期限の特例）")
        self.assertIn("期限の特例を定める", second["text"])

    def test_relation_style_appendix_is_parsed_and_not_merged_into_supplement(self) -> None:
        data = parse_honbun(RELATION_APPENDIX, law_id="r122RG00000070", source_url="https://example.invalid/rel.html")
        self.assertEqual(len(data["appendix_tables"]), 1)
        self.assertTrue(data["appendix_tables"][0].startswith("別表(第2条関係)"))
        self.assertIn("納税証明", data["appendix_tables"][0])
        self.assertEqual(len(data["supplements"]), 1)
        self.assertNotIn("納税証明", data["supplements"][0])
        self.assertNotIn("別表", data["supplements"][0])
        self.assertEqual(data["parse_warnings"], [])

    def test_history_ignores_appendix_shaped_rows(self) -> None:
        data = parse_honbun(HISTORY_TABLE_WITH_APPENDIX_SHAPE, law_id="r122RG00000070", source_url="https://example.invalid/hist.html")
        self.assertEqual(data["history"], [{"date": "平成17年4月1日", "number": "条例第51号"}])

    def test_history_is_empty_with_warning_when_no_history_table(self) -> None:
        html = """
<html><head><title>東松島市沿革なし条例</title></head><body>
<div id="primary" class="joubun"><div><p><span>第1条</span>　<span>本文である。</span></p></div></div><!-- /本文 -->
<table><tr><td>1</td><td>別表の行</td></tr></table>
</body></html>
"""
        data = parse_honbun(html, law_id="r122RG00000070", source_url="https://example.invalid/nohist.html")
        self.assertEqual(data["history"], [])
        self.assertEqual(data["appendix_tables"], [])


if __name__ == "__main__":
    unittest.main()


CHAPTER_LAW = """
<html><head><title>東松島市テスト要綱</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><div class="head"><p><span>○東松島市テスト要綱</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>令和7年4月1日</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>訓令甲第1号</span></p></div></div></div>
<div><div class="eline"><div class="chapter"><p class="num"><span>第1章</span>　<span>総則</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(趣旨)</span></p><p><span>第1条</span>　<span>この要綱は、テストに関する事項を定める。</span></p></div></div></div>
<div><div class="eline"><div class="chapter"><p class="num"><span>第2章</span>　<span>組織</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(組織)</span></p><p><span>第2条</span>　<span>組織は、次に掲げる職員をもって構成する。</span></p></div></div></div>
<div><div class="eline"><div class="clause"><p><span>2</span>　<span>前項の組織は、別に定める。</span></p></div></div></div>
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市テスト要綱</h2>
<p class="datenumber-area mt04">令和7年4月1日　訓令甲第1号</p>
<span class="taikei-item">第1編 総規/第1章 市制施行</span></div>
</body></html>
"""

FORM_LAW = """
<html><head><title>東松島市テスト規則</title></head><body>
<div id="primary" class="joubun showhistory"><div id="primaryInner"><div id="primaryInner2">
<div><div class="eline"><div class="head"><p><span>○東松島市テスト規則</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>令和7年4月1日</span></p></div></div></div>
<div><div class="eline"><div class="head"><p><span>規則第1号</span></p></div></div></div>
<div><div class="eline"><div class="article"><p class="title"><span>(趣旨)</span></p><p><span>第1条</span>　<span>この規則は、テストに関する事項を定める。</span></p></div></div></div>
<div><div class="eline"><div class="form_section"><p class="num"><a onClick="fileDownloadAction2('word/r122FG00000001.rtf');return false;" href="javascript:void(0);"><span>別表第1</span><span>(第1条関係)</span></a></p></div></div></div>
<div><div class="eline"><div id="e000000099" class="xref_frame cm"><p><img src="word/r122FG00000001s.png" alt="画像" class="xref_thumb"/></p></div></div></div>
</div></div></div><!-- /本文 -->
<div id="secondary"><h2 class="heading-lv2A">東松島市テスト規則</h2>
<p class="datenumber-area mt04">令和7年4月1日　規則第1号</p>
<span class="taikei-item">第1編 総規/第1章 市制施行</span></div>
</body></html>
"""


class ChapterAndResourceTest(unittest.TestCase):
    def test_chapters_are_not_mixed_into_article_paragraphs(self) -> None:
        data = parse_honbun(CHAPTER_LAW, law_id="r122RG00001013", source_url="https://example.invalid/1013.html")
        chapters = data.get("chapters") or []
        self.assertEqual([c["text"] for c in chapters], ["第1章 総則", "第2章 組織"])
        first, second = data["articles"]
        self.assertEqual(first["chapter"], "第1章")
        self.assertEqual(first["chapter_title"], "総則")
        self.assertEqual(second["chapter"], "第2章")
        for article in data["articles"]:
            for paragraph in article["paragraphs"]:
                self.assertNotIn("第1章", paragraph["text"])
                self.assertNotIn("第2章", paragraph["text"])
                self.assertNotIn("第1章", article["text"])
        self.assertEqual([w for w in data["parse_warnings"] if w.startswith("chapter_heading")], [])

    def test_form_resources_are_preserved_and_flagged(self) -> None:
        data = parse_honbun(FORM_LAW, law_id="r122RG00000308", source_url="https://example.invalid/308.html")
        resources = data.get("resources") or []
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["href"], "word/r122FG00000001.rtf")
        self.assertEqual(resources[0]["image_url"], "word/r122FG00000001s.png")
        self.assertTrue(
            any(w.startswith("external_resource_only:") for w in data["parse_warnings"]),
            data["parse_warnings"],
        )
        # The heading is still published so the table stays discoverable.
        self.assertTrue(any("別表第1" in table for table in data["appendix_tables"]))


class AppendixResourceMapTest(unittest.TestCase):
    def test_branch_tables_are_distinct_from_their_parent(self) -> None:
        self.assertEqual(appendix_table_key("別表第1(第2条関係)"), (1, 0))
        self.assertEqual(appendix_table_key("別表第1―1"), (1, 1))
        self.assertEqual(appendix_table_key("別表第1の2"), (1, 2))
        self.assertIsNone(appendix_table_key("別表(第2条関係)"))

    def test_branch_rows_map_to_their_own_resources(self) -> None:
        tables = ["別表第1(第2条関係)", "別表第1―1", "別表第1―2"]
        resources = [
            {"label": "様式第1号(第3条関係)", "kind": "form"},
            {"label": "別表第1―2", "kind": "appendix"},
            {"label": "別表第1", "kind": "appendix"},
        ]
        self.assertEqual(build_resource_map(tables, resources), [2, None, 1])

    def test_unnumbered_table_takes_the_next_appendix_resource(self) -> None:
        tables = ["別表(第2条関係)"]
        resources = [
            {"label": "様式第1号(第3条関係)", "kind": "form"},
            {"label": "別表", "kind": "appendix"},
        ]
        self.assertEqual(build_resource_map(tables, resources), [1])


class StyleSectionBoundaryTest(unittest.TestCase):
    def test_heading_form_matches(self) -> None:
        self.assertIsNotNone(STYLE_SECTION_RE.match("様式第1号(第14条関係)"))
        self.assertIsNotNone(STYLE_SECTION_RE.match("様式第1号の2（第3条関係）"))
        self.assertIsNotNone(STYLE_SECTION_RE.match("様式第1号"))

    def test_wrapped_prose_is_not_a_heading(self) -> None:
        self.assertIsNone(STYLE_SECTION_RE.match("様式第1号により定める。"))
        self.assertIsNone(STYLE_SECTION_RE.match("様式は別に定める。"))


class AmendmentEraTest(unittest.TestCase):
    def test_abbreviated_meiji_and_taisho_notes_are_recognised(self) -> None:
        self.assertTrue(is_amendment_note("(明42訓令甲3・一部改正)"))
        self.assertTrue(is_amendment_note("(大11訓令甲1・一部改正)"))
        self.assertTrue(is_amendment_note("(令8訓令甲23・一部改正)"))
