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

PAREN_ITEM_FULLWIDTH = (
    PAREN_ITEM.replace("(市の休日)", "（市の休日）")
    .replace("(3)", "（3）")
    .replace("(前号に掲げる日を除く。)", "（前号に掲げる日を除く。）")
    .replace("(期限の特例)", "（期限の特例）")
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


def primary_page(title: str, body: str) -> str:
    return (
        f"<!DOCTYPE html>\n<html><head><title>{title}</title></head>\n<body>\n"
        f'<div id="primary">\n{body}\n<!-- /本文 -->\n</div>\n</body></html>'
    )


def toc_row(cls: str, number: str, title: str, articles: str = "") -> str:
    range_span = f'<span class="p cm">{articles}</span>' if articles else ""
    return (
        f'<div><div class="eline"><div class="in-chapter"><p class="{cls}">'
        f'<span class="num cm">{number}</span>\u3000<span class="title cm">{title}</span>{range_span}'
        "</p></div></div></div>\n"
    )


def body_heading(kind: str, number: str, title: str) -> str:
    return (
        f'<div><div class="eline"><div class="{kind}"><p class="num">'
        f'<span class="num cm">{number}</span>\u3000<span class="title cm">{title}</span>'
        "</p></div></div></div>\n"
    )


def toc_article(label: str, heading: str, body: str) -> str:
    return (
        '<div><div class="eline"><div class="article">'
        f'<p class="title"><span class="cm">{heading}</span></p>'
        f'<p class="num"><span class="num cm">{label}</span>\u3000<span class="clause">'
        f'<span class="p cm">{body}</span></span></p>'
        "</div></div></div>\n"
    )


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
        for variant, html, expected_suffix in (
            ("halfwidth", PAREN_ITEM, "(前号に掲げる日を除く。)"),
            ("fullwidth", PAREN_ITEM_FULLWIDTH, "（前号に掲げる日を除く。）"),
        ):
            with self.subTest(variant=variant):
                data = parse_honbun(html, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
                article = data["articles"][0]
                items = article["paragraphs"][0]["items"]
                self.assertEqual([item["label"] for item in items], ["(1)", "(2)", "(3)"])
                self.assertTrue(items[2]["text"].endswith(expected_suffix))
                self.assertEqual(data["parse_warnings"], [])
        half = parse_honbun(PAREN_ITEM, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
        self.assertIn("(3) 12月29日から翌年の1月3日までの日(前号に掲げる日を除く。)", half["articles"][0]["text"])
        self.assertEqual(half["articles"][1]["heading"], "(期限の特例)")

    def test_nested_and_mixed_parentheses_headings(self) -> None:
        for heading in ("(職員（非常勤）の勤務)", "（職員(非常勤)の勤務）"):
            with self.subTest(heading=heading):
                html = PAREN_ITEM.replace("(期限の特例)", heading)
                data = parse_honbun(html, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
                self.assertEqual(data["articles"][1]["heading"], heading)
                self.assertEqual(data["parse_warnings"], [])

    def test_inline_mixed_parentheses_headings(self) -> None:
        cases = (
            ("（職員(非常勤)の勤務）", "職員の勤務条件は、別に定める。"),
            ("(職員（非常勤）の勤務)", "職員の勤務条件は、別に定める。"),
            ("(見出し）", "見出しに続く本文である。"),
            ("（見出し)", "見出しに続く本文である。"),
            ("（職員(非常勤）の勤務）", "職員の勤務条件は、別に定める。"),
        )
        for heading, body in cases:
            with self.subTest(heading=heading):
                html = PAREN_ITEM.replace(
                    "<p><span>第2条</span>　<span>期限の特例を定める。</span></p>",
                    f"<p><span>第2条</span>　<span>{heading}{body}</span></p>",
                )
                data = parse_honbun(html, law_id="r122RG00000002", source_url="https://example.invalid/2.html")
                article = data["articles"][1]
                self.assertEqual(article["heading"], heading)
                self.assertEqual(article["paragraphs"][0]["text"], body)
                self.assertEqual(data["parse_warnings"], [])

    def test_unnumbered_ordinance(self) -> None:
        data = parse_honbun(UNNUMBERED, law_id="r122RG00000001", source_url="https://example.invalid/1.html")
        self.assertEqual(data["article_count"], 0)
        self.assertIn("上河戸36番地1", data["body_text"])
        self.assertEqual(data["parse_warnings"], [])


class ParseWarningAndIntegrityTest(unittest.TestCase):
    def test_item_structure_mismatch_and_empty_body_warnings(self) -> None:
        mismatch = parse_honbun(ITEM_MISMATCH, law_id="r122RG00000002", source_url="https://example.invalid/mismatch.html")
        self.assertTrue(
            any(w.startswith("item_structure_mismatch:第1条:") for w in mismatch["parse_warnings"]),
            mismatch["parse_warnings"],
        )
        empty = parse_honbun(EMPTY_BODY, law_id="r122RG00000002", source_url="https://example.invalid/empty.html")
        self.assertEqual(empty["article_count"], 0)
        self.assertIn("no_articles_parsed", empty["parse_warnings"])

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

    def test_history_ignores_appendix_shaped_rows_and_handles_missing_history(self) -> None:
        data = parse_honbun(HISTORY_TABLE_WITH_APPENDIX_SHAPE, law_id="r122RG00000070", source_url="https://example.invalid/hist.html")
        self.assertEqual(data["history"], [{"date": "平成17年4月1日", "number": "条例第51号"}])
        nohist = """
<html><head><title>東松島市沿革なし条例</title></head><body>
<div id="primary" class="joubun"><div><p><span>第1条</span>　<span>本文である。</span></p></div></div><!-- /本文 -->
<table><tr><td>1</td><td>別表の行</td></tr></table>
</body></html>
"""
        empty_hist = parse_honbun(nohist, law_id="r122RG00000070", source_url="https://example.invalid/nohist.html")
        self.assertEqual(empty_hist["history"], [])
        self.assertEqual(empty_hist["appendix_tables"], [])


class ChapterAndResourceTest(unittest.TestCase):
    def test_chapters_are_not_mixed_into_article_paragraphs(self) -> None:
        data = parse_honbun(CHAPTER_LAW, law_id="r122RG00001013", source_url="https://example.invalid/1013.html")
        self.assertEqual([c["text"] for c in data.get("chapters") or []], ["第1章 総則", "第2章 組織"])
        first, second = data["articles"]
        self.assertEqual((first["chapter"], first["chapter_title"]), ("第1章", "総則"))
        self.assertEqual(second["chapter"], "第2章")
        for article in data["articles"]:
            self.assertNotIn("第1章", article["text"])
            for paragraph in article["paragraphs"]:
                self.assertNotIn("第1章", paragraph["text"])
                self.assertNotIn("第2章", paragraph["text"])
        self.assertEqual([w for w in data["parse_warnings"] if w.startswith("chapter_heading")], [])

    def test_form_resources_and_mapping(self) -> None:
        data = parse_honbun(FORM_LAW, law_id="r122RG00000308", source_url="https://example.invalid/308.html")
        resources = data.get("resources") or []
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["href"], "word/r122FG00000001.rtf")
        self.assertEqual(resources[0]["image_url"], "word/r122FG00000001s.png")
        self.assertTrue(any(w.startswith("external_resource_only:") for w in data["parse_warnings"]))
        self.assertTrue(any("別表第1" in table for table in data["appendix_tables"]))

        self.assertEqual(appendix_table_key("別表第1(第2条関係)"), (1, 0))
        self.assertEqual(appendix_table_key("別表第1―1"), (1, 1))
        self.assertEqual(appendix_table_key("別表第1の2"), (1, 2))
        self.assertIsNone(appendix_table_key("別表(第2条関係)"))

        self.assertEqual(
            build_resource_map(
                ["別表第1(第2条関係)", "別表第1―1", "別表第1―2"],
                [
                    {"label": "様式第1号(第3条関係)", "kind": "form"},
                    {"label": "別表第1―2", "kind": "appendix"},
                    {"label": "別表第1", "kind": "appendix"},
                ],
            ),
            [2, None, 1],
        )
        self.assertEqual(
            build_resource_map(
                ["別表(第2条関係)"],
                [{"label": "様式第1号(第3条関係)", "kind": "form"}, {"label": "別表", "kind": "appendix"}],
            ),
            [1],
        )


class AmendmentAndStyleTest(unittest.TestCase):
    HTML_AMENDMENT = primary_page(
        "東松島市災害対策本部運営要綱",
        '<div class="chapter"><p class="num"><span>第2章</span> <span>本部</span></p></div>\n'
        "<p>第10条 本章は、災害対策本部の設置について定める。</p>\n"
        "<p>第11条 本部長は、本部の事務を総括する。</p>\n"
        "<p>(令8訓令甲23・一部改正)</p>\n"
        '<div class="chapter"><p class="num"><span>第3章</span> <span>非常配備態勢</span></p></div>\n'
        "<p>第12条 副本部長は、本部長を補佐する。</p>",
    )

    HTML_MIXED = primary_page(
        "東松島市災害対策本部運営要綱",
        "<p>第3条 別表に掲げる基準による。</p>\n"
        "<p>別表第1(第3条関係) 被害認定基準</p>\n"
        "<p>1 全壊 50パーセント以上</p>\n"
        '<div class="form_section"><p class="num"><a href="#" onClick="fileDownloadAction2(\'honbun_1.rtf\')">'
        "<span>様式第1号</span><span>(第14条関係)</span></a></p></div>\n"
        '<div class="form_section"><p class="num"><a href="#" onClick="fileDownloadAction2(\'honbun_2.rtf\')">'
        "<span>別表第2</span><span>(第5条関係)</span></a></p></div>\n"
        '<div id="e1" class="xref_frame cm"><p><img src="/reiki/honbun_1.png"></p></div>\n'
        '<div id="e2" class="xref_frame cm"><p><img src="/reiki/honbun_2.png"></p></div>',
    )

    def test_amendment_note_detection_across_eras(self) -> None:
        for note in (
            "(明42訓令甲3・一部改正)",
            "(大11訓令甲1・一部改正)",
            "(令8訓令甲23・一部改正)",
            "（平成30条例第12号）",
            "(令5訓令甲3・全部改正)",
        ):
            self.assertTrue(is_amendment_note(note), note)
        for non_note in ("(目的)", "(貸付条件)", "第12条の2))"):
            self.assertFalse(is_amendment_note(non_note), non_note)

    def test_amendment_note_stays_in_article_and_keeps_chapter(self) -> None:
        law = parse_honbun(self.HTML_AMENDMENT, law_id="r122RG00001013", source_url="https://example.test/1013.html")
        by_label = {a["label"]: a for a in law["articles"]}
        self.assertEqual(list(by_label), ["第10条", "第11条", "第12条"])
        self.assertEqual((by_label["第10条"]["heading"], by_label["第12条"]["heading"]), ("", ""))
        self.assertIn("一部改正", by_label["第11条"]["text"])
        self.assertNotIn("一部改正", by_label["第12条"]["text"])
        self.assertEqual(by_label["第10条"]["chapter"], "第2章")
        self.assertEqual((by_label["第12条"]["chapter"], by_label["第12条"]["chapter_title"]), ("第3章", "非常配備態勢"))

        plain = parse_honbun(
            primary_page("要綱", "<p>(目的)</p>\n<p>第1条 この要綱は、本部の運営について定める。</p>"),
            law_id="r122RG00001013",
            source_url="https://example.test/1013.html",
        )
        self.assertEqual(plain["articles"][0]["heading"], "(目的)")

    def test_style_sections_and_appendix_resource_index(self) -> None:
        law = parse_honbun(self.HTML_MIXED, law_id="r122RG00001013", source_url="https://example.test/1013.html")
        self.assertEqual(len(law["appendix_tables"]), 2)
        self.assertTrue(law["appendix_tables"][0].startswith("別表第1"))
        self.assertTrue(law["appendix_tables"][1].startswith("別表第2"))
        self.assertNotIn("様式第1号", law["appendix_tables"][0])
        self.assertTrue(law["appendix_styles"][0].startswith("様式第1号"))
        self.assertEqual(len(law["resources"]), 2)
        form, table = law["resources"]
        self.assertEqual((form["kind"], form["table_number"], form["seq"]), ("form", None, 1))
        self.assertEqual((table["kind"], table["table_number"], table["image_url"]), ("appendix", 2, "/reiki/honbun_2.png"))
        self.assertEqual(law["appendix_table_resource_index"], [None, 1])

    def test_style_section_boundary(self) -> None:
        for heading in ("様式第1号(第14条関係)", "様式第1号の2（第3条関係）", "様式第1号"):
            self.assertIsNotNone(STYLE_SECTION_RE.match(heading), heading)
        for prose in ("様式第1号により定める。", "様式は別に定める。"):
            self.assertIsNone(STYLE_SECTION_RE.match(prose), prose)


class TocAlignmentTest(unittest.TestCase):
    HTML = primary_page(
        "東松島市立学校の管理に関する規則",
        '<div><div class="eline"><div class="toc"><p class="title"><span class="cm">目次</span></p></div></div></div>\n'
        + toc_row("toc_item-chapter", "第1章", "総則", "(第1条)")
        + toc_row("toc_item-chapter", "第2章", "小学校及び中学校")
        + toc_row("toc_item-section", "第1節", "学年、学期及び休業日", "(第2条―第5条)")
        + toc_row("toc_item-section", "第4節", "学校の組織編成", "(第6条)")
        + '<div><div class="eline"><div class="in-chapter"><p class="toc_item-supplement"><span class="p cm">附則</span></p></div></div></div>\n'
        + body_heading("chapter", "第1章", "総則")
        + toc_article("第1条", "(目的)", "この規則は、小学校及び中学校の管理運営について定める。")
        + body_heading("chapter", "第2章", "小学校及び中学校")
        + body_heading("section", "第1節", "学年、学期及び休業日")
        + toc_article("第2条", "(学年及び学期)", "学年は、4月1日に始まり、翌年3月31日に終わる。")
        + toc_article("第3条", "(休業日)", "休業日は、次に掲げるとおりとする。")
        + body_heading("section", "第4節", "学校の組織編制")
        + toc_article("第6条", "(組織)", "学校に、校長、教頭及び教諭を置く。")
        + '<div><div class="eline"><p class="p">附則</p></div></div>\n'
        + '<div><div class="eline"><p class="p">この規則は、公布の日から施行する。</p></div></div>',
    )

    @classmethod
    def setUpClass(cls) -> None:
        cls.law = parse_honbun(cls.HTML, law_id="r122RG00000093", source_url="https://example.test/reiki_honbun/r122RG00000093.html")
        cls.by_label = {a["label"]: a for a in cls.law["articles"]}

    def test_toc_does_not_corrupt_chapters_sections_supplements_or_articles(self) -> None:
        first = self.by_label["第1条"]
        self.assertEqual((first["chapter"], first["chapter_title"], first["section"]), ("第1章", "総則", ""))
        second = self.by_label["第2条"]
        self.assertEqual((second["chapter"], second["chapter_title"], second["section"], second["section_title"]), ("第2章", "小学校及び中学校", "第1節", "学年、学期及び休業日"))
        sixth = self.by_label["第6条"]
        self.assertEqual((sixth["chapter"], sixth["section"], sixth["section_title"]), ("第2章", "第4節", "学校の組織編制"))
        self.assertEqual(len(self.law["supplements"]), 1)
        self.assertTrue(self.law["supplements"][0].startswith("附則"))
        self.assertEqual([w for w in self.law["parse_warnings"] if w.startswith("chapter_heading_unstructured")], [])
        titles = [c["title"] for c in self.law["chapters"]]
        self.assertIn("学校の組織編制", titles)
        self.assertNotIn("学校の組織編成", titles)
        for article in self.law["articles"]:
            text = article.get("text") or ""
            self.assertNotIn("目次", text)
            self.assertNotIn("第2章", text)



class ArticleBranchChainAndSupplementTest(unittest.TestCase):
    """Issues #95 and #97: keep multi-level branches and keep supplement articles out of body."""

    FIXTURE_95_97 = primary_page(
        "東松島市テスト規則",
        '<div><div class="eline"><div class="head"><p><span>○東松島市テスト規則</span></p></div></div></div>\n'
        '<div><div class="eline"><div class="head"><p><span>令和7年4月1日</span></p></div></div></div>\n'
        '<div><div class="eline"><div class="head"><p><span>規則第1号</span></p></div></div></div>\n'
        '<div><div class="eline"><div class="article"><p class="title"><span>(基本給)</span></p><p><span>第9条の2</span>　<span>基本給は、この規則の定めるところによる。</span></p></div></div></div>\n'
        '<div><div class="eline"><div class="article"><p class="title"><span>(級別定数)</span></p><p><span>第9条の2の2</span>　<span>級別定数は、別表第2に定めるところによる。</span></p></div></div></div>\n'
        '<div><div class="eline"><div class="article"><p class="title"><span>(削除)</span></p><p><span>第9条の2の3</span>　<span>削除</span></p></div></div></div>\n'
        '<div><div class="eline"><p><span><span class="word-space">附</span>則</span></p></div></div>\n'
        '<div><div class="eline"><div class="head"><p><span>(施行期日)</span></p></div></div></div>\n'
        '<div><div class="eline"><p><span><span>第1条</span>　<span>この規則は、令和7年4月1日から施行する。</span></p></div></div></div>\n'
        '<div><div class="eline"><p><span><span>第2条</span>　<span>この規則の施行に関し必要な経過措置は、市長が定める。</span></p></div></div></div>',
    )

    def test_two_level_branch_labels_and_supplement_isolation(self) -> None:
        law = parse_honbun(self.FIXTURE_95_97, law_id="r122RG00000999", source_url="https://example.test/999")
        labels = [article["label"] for article in law["articles"]]
        self.assertEqual(labels, ["第9条の2", "第9条の2の2", "第9条の2の3"])
        self.assertEqual(len(labels), len(set(labels)))
        for article in law["articles"]:
            first = article["paragraphs"][0]["text"] if article["paragraphs"] else ""
            self.assertFalse(first.startswith("の"), article)
        self.assertIsNotNone(STYLE_SECTION_RE.match("様式第5号の1の2"))
        self.assertIsNotNone(STYLE_SECTION_RE.match("様式第5号の1"))
        supplements = law["supplements"]
        self.assertEqual(len(supplements), 1)
        self.assertIn("第1条", supplements[0])
        self.assertIn("令和7年4月1日から施行する", supplements[0])
        self.assertIn("第2条", supplements[0])


if __name__ == "__main__":
    unittest.main()
