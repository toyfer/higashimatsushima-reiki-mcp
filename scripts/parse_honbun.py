#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reiki_common import html_to_text

PRIMARY_RE = re.compile(r'<div id="primary".*?<!-- /本文 -->', re.S)
# The page repeats every structural heading in a table of contents before the
# body. TOC rows are <p class="toc_item-chapter"> / "toc_item-section" /
# "toc_item-supplement" and may or may not carry a (第N条―第M条) range, so they
# must not reach the line list: a TOC row consumed a chapter entry and shifted
# every article's chapter/section (issue #81).
TOC_ITEM_RE = re.compile(r'<p[^>]*class="toc_item[^"]*"[^>]*>.*?</p>', re.S)
TOC_TITLE_RE = re.compile(r'<div class="toc">.*?</div>', re.S)
TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
SECONDARY_TITLE_RE = re.compile(r'<h2 class="heading-lv2A">(.*?)</h2>', re.S)
DATENUMBER_RE = re.compile(r'<p class="datenumber-area[^"]*">(.*?)</p>', re.S)
TAIKEI_RE = re.compile(r'<span class="taikei-item">(.*?)</span>\s*</div>', re.S)
ENKAKU_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
# The history table lives in the 書誌情報 tab, not in the body. Reading every
# <tr> on the page pulled appendix table rows into history (issue #36).
HISTORY_SCOPE_RE = re.compile(r'<div id="shoshi-inf".*?(?:<!-- /書誌情報 -->|</div>\s*</div>)', re.S)
HISTORY_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S)
HISTORY_DATE_RE = re.compile(r"^(?:(?:明治|大正|昭和|平成|令和)[0-9０-９元]+年|(?:19|20)[0-9]{2}年)")
# The number cell also carries document kinds such as 訓令甲第28号, so require
# a 第N号 tail rather than a fixed prefix list.
HISTORY_NUMBER_RE = re.compile(r"^[^\s]{0,30}第[0-9０-９]+号$")
# 「第9条の2の2」「第36条の3の2」のように枝番が 2 段以上続く例規がある。
# 1 段だけを許すと番号が切り詰められ、ラベルが衝突して本文先頭に「の2」が残る (issue #97)。
ARTICLE_START_RE = re.compile(r"^第([0-9０-９]+)条((?:の[0-9０-９]+)*)\s*(.*)$")
HEADING_LINE_RE = re.compile(r"^[\(（].+[\)）]$")
SUPPLEMENT_RE = re.compile(r"^附\s*則")
# Structural headings. The city marks chapters with <div class="chapter"><p
# class="num"><span>第N章</span><span>見出し</span></p></div> in the body and
# section headings the same way (issue #50). Without this, chapter/section
# headings were flattening into the previous article's paragraph text.
CHAPTER_LINE_RE = re.compile(r"^第([0-9０-９一二三四五六七八九十]+)章\s*(.*)$")
SECTION_LINE_RE = re.compile(r"^第([0-9０-９一二三四五六七八九十]+)節\s*(.*)$")
# A body heading line can carry the table-of-contents article range
# ("第4節 学校の組織編成(第18条―第29条)") or a deletion marker ("第5節 鉱産税 削除")
# that the chapter <div> does not. Both are noise when comparing a line with the
# structure collected from the body HTML (issue #50).
HEADING_RANGE_RE = re.compile(
    r"[\(（]\s*第[0-9０-９一二三四五六七八九十百]+条(?:\s*[―–\-~〜]\s*第[0-9０-９一二三四五六七八九十百]+条)?\s*[\)）]\s*$"
)
# "(削除)", "削除" and "・削除" all mean the provision is gone, not that the
# heading was lost, so the parser records it instead of warning.
DELETED_HEADING_RE = re.compile(r"(?:[\(（]?\s*削除\s*[\)）]?|・\s*削除)\s*$")
CHAPTER_HTML_RE = re.compile(
    r'<div class="(?:chapter|section)"><p[^>]*class="num">\s*<span[^>]*>([^<]+)</span>\s*<span[^>]*>([^<]*)</span>',
    re.S,
)
# Appendix / form tables served as downloadable files render as a form_section
# heading plus an <img> thumbnail (issue #51). html_to_text drops the file
# links, so collect them separately from the raw body HTML.
FORM_SECTION_RE = re.compile(
    r'<div class="form_section"><p[^>]*class="num">\s*<a[^>]*onClick="fileDownloadAction2\(\'([^\']+)\'\)[^>]*>\s*<span[^>]*>([^<]+)</span>\s*<span[^>]*>([^<]*)</span>',
    re.S,
)
XREF_IMG_RE = re.compile(r'<div id="e[0-9]+" class="xref_frame cm"><p><img src="([^"]+)', re.S)
APPENDIX_TABLE_RE = re.compile(r"^別表")
# 別表第1 and 別表(第2条関係) are both used by the city site; the second form
# was silently appended to the last supplement (issue #38).
# Table titles appear as 別表, 別表第1, 別表1(第2条関係) and 別表(第2条関係).
APPENDIX_START_RE = re.compile(r"^別表(?:第?[0-9０-９]+|\s|[\(（]|$)")
# Prose such as 別表に掲げる… must stay body text and must not raise a warning.
APPENDIX_TITLE_HINT_RE = re.compile(r"^別表[0-9０-９第\(（]")
# 様式第N号 sections are separate forms, not a continuation of the table that
# happens to precede them (issue #61). Anchored on the 号 or an opening paren so
# ordinary prose such as 様式は… stays body text.
# 様式第1号により… wrapped to the start of a line is prose, not a heading, so
# the pattern only fires when the 号 is followed by the end of the line, a
# space, or an opening paren.
STYLE_SECTION_RE = re.compile(r"^様式(?:第?[0-9０-９]+号(?:(?:の|[-－―‐‑])[0-9０-９]+)*(?=\s|[\(（]|$)|[\(（])")
# 別表第1―1 and 別表第1の1 are sub-tables of 別表第1, so the branch number is
# part of the identity: matching only the main number made every branch collide
# with its parent (issue #61 review).
APPENDIX_NUMBER_RE = re.compile(r"^別表(?:第)?([0-9０-９]+)(?:(?:の|[-－―‐‑])([0-9０-９]+))?")
PARAGRAPH_RE = re.compile(r"^([0-9０-９]+)\s+(.+)$")
ITEM_RE = re.compile(r"^[\(（]([0-9０-９]+)[\)）]\s*(.*)$")
SUBITEM_RE = re.compile(r"^([アイウエオカキクケコサシスセソタチツテト])\s*(.*)$")
DATE_NUMBER_SPLIT_RE = re.compile(r"^(.*?)\s+(.+)$")
# Amendment notes such as (令8訓令甲23・一部改正) are parenthesised exactly like
# a heading, so they were captured as deferred headings and, when a chapter
# heading sat between them and the next article, became that article's heading
# while also disappearing from the amended article's text (issue #61).
# The city site abbreviates eras (令8, 平30, 昭62), so both the short and the
# full form must be accepted.
AMENDMENT_ERA_RE = re.compile(r"^[\(（](?:明治|明|大正|大|昭和|昭|平成|平|令和|令)\s*(?:[0-9０-９]+|元)")
AMENDMENT_WORD_RE = re.compile(r"(?:一部改正|全部改正|全改|改正|改定|追加|削除|新旧対照)")
AMENDMENT_NUMBER_RE = re.compile(r"第[0-9０-９]+号[\)）]$")

ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def to_int(value: str) -> int:
    return int(value.translate(ZEN))


def is_amendment_note(line: str) -> bool:
    """True for a parenthesised amendment note such as (令8訓令甲23・一部改正)."""
    if not AMENDMENT_ERA_RE.match(line):
        return False
    if AMENDMENT_WORD_RE.search(line):
        return True
    return bool(AMENDMENT_NUMBER_RE.search(line))


def appendix_table_key(label: str) -> tuple[int, int] | None:
    """Identify an appendix table as (main number, branch number).

    The branch is 0 for 別表第1, 1 for 別表第1―1 and 別表第1の1, so a sub-table
    can never be confused with its parent or with another parent's child.
    """
    match = APPENDIX_NUMBER_RE.match(str(label or "").strip())
    if not match:
        return None
    branch = to_int(match.group(2)) if match.group(2) else 0
    return (to_int(match.group(1)), branch)


def appendix_table_number(label: str) -> int | None:
    key = appendix_table_key(label)
    return key[0] if key else None


def appendix_table_branch(label: str) -> int | None:
    key = appendix_table_key(label)
    return key[1] if key else None


def clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\xa0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", value).strip().lstrip("○").strip()


def extract_lines(html: str) -> tuple[list[str], str]:
    match = PRIMARY_RE.search(html)
    scope = match.group(0) if match else html
    text = html_to_text(TOC_TITLE_RE.sub("", TOC_ITEM_RE.sub("", scope)))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines, scope


_PAREN_OPENS = {"(", "（"}
_PAREN_CLOSES = {")", "）"}


def split_leading_heading(rest: str) -> tuple[str, str]:
    # Japanese ordinance headings mix full-width （） and half-width () freely,
    # including mismatched pairs such as (見出し）.  Count nesting depth across
    # both widths instead of requiring each close to match its opener's width,
    # so nested headings stay intact while legacy mismatched pairs still split.
    if not rest or rest[0] not in _PAREN_OPENS:
        return "", rest
    depth = 0
    for index, char in enumerate(rest):
        if char in _PAREN_OPENS:
            depth += 1
        elif char in _PAREN_CLOSES:
            depth -= 1
            if depth == 0:
                return rest[: index + 1], rest[index + 1 :].strip()
            if depth < 0:
                return "", rest
    return "", rest


def heading_identity(text: str) -> tuple[str, bool]:
    """Return a heading line without TOC noise, and whether it is deleted.

    ``第4節 学校の組織編成(第18条―第29条)`` is the table-of-contents spelling of a
    heading the body carries without the range, and ``第5節 鉱産税 削除`` is a
    section whose text was removed. Comparing the raw line with the body
    structure failed for both and raised a spurious warning (issue #50).
    """
    base = HEADING_RANGE_RE.sub("", text).strip()
    deleted = bool(DELETED_HEADING_RE.search(base))
    if deleted:
        base = DELETED_HEADING_RE.sub("", base).strip()
    return base, deleted


def parse_chapters(scope: str) -> list[dict[str, str]]:
    """Collect structural headings from the body scope only.

    The page TOC renders the same headings as <div class="in-chapter">, which
    teams up with a "(第N条―第M条)" range. The body copy in <div
    class="chapter"> carries no range, only number and title, so it is the
    authoritative one for article metadata.
    """
    chapters: list[dict[str, str]] = []
    for number, title in CHAPTER_HTML_RE.findall(scope):
        label = re.sub(r"\s+", " ", number).strip()
        heading = re.sub(r"\s+", " ", title).strip()
        if not label:
            continue
        is_section = label.endswith("節")
        chapters.append(
            {
                "kind": "section" if is_section else "chapter",
                "number": label,
                "title": heading,
                "text": f"{label} {heading}".strip(),
            }
        )
    return chapters


def parse_resources(scope: str, source_url: str) -> list[dict[str, Any]]:
    """Collect RTF/PNG form resources referenced by appendix headings."""
    resources: list[dict[str, Any]] = []
    images = [m.group(1) for m in XREF_IMG_RE.finditer(scope)]
    for position, (href, name, suffix) in enumerate(FORM_SECTION_RE.findall(scope), start=1):
        label = f"{name}{suffix}".strip()
        image = ""
        if position - 1 < len(images):
            image = images[position - 1]
        # Attach the thumbnail whose base matches the RTF file name.
        if not image and href:
            stem = href.rsplit(".", 1)[0]
            for candidate in images:
                if stem and candidate.startswith(stem):
                    image = candidate
                    break
        # Identity, not just order: appendix tables and 様式 share this list but
        # do not correspond to law.appendix_tables one-to-one (issue #61).
        kind = "appendix" if label.startswith("別表") else "form"
        resources.append(
            {
                "label": label,
                "kind": kind,
                "table_number": appendix_table_number(label) if kind == "appendix" else None,
                "table_branch": appendix_table_branch(label) if kind == "appendix" else None,
                "seq": position,
                "href": href,
                "image_url": image,
                "source_url": source_url,
            }
        )
    return resources


def build_resource_map(appendix_tables: list[str], resources: list[dict[str, Any]]) -> list[int | None]:
    """Map each appendix table to the resource that belongs to it.

    ``law.resources[n - 1]`` assumed the two lists line up in length and order,
    which breaks as soon as HTML tables and form_section (RTF/PNG) tables are
    mixed in one ordinance (issue #61). Match on the full 別表 key, branch
    number included, and let an unnumbered 別表 take the next unclaimed
    appendix resource in document order. Anything left over stays null.
    """
    by_key: dict[tuple[int, int], int] = {}
    unnumbered: list[int] = []
    for position, resource in enumerate(resources):
        if resource.get("kind") != "appendix":
            continue
        key = appendix_table_key(str(resource.get("label") or ""))
        if key is None:
            unnumbered.append(position)
        elif key not in by_key:
            by_key[key] = position
    mapping: list[int | None] = []
    for table in appendix_tables:
        key = appendix_table_key(table)
        if key is not None:
            mapping.append(by_key.get(key))
            continue
        mapping.append(unnumbered.pop(0) if unnumbered else None)
    return mapping


def history_scope(html: str) -> str | None:
    match = HISTORY_SCOPE_RE.search(html)
    return match.group(0) if match else None


def parse_history(html: str) -> list[dict[str, str]]:
    scope = history_scope(html)
    if scope is None:
        return []
    table = HISTORY_TABLE_RE.search(scope)
    if table is None:
        return []
    history: list[dict[str, str]] = []
    for row in ENKAKU_ROW_RE.findall(table.group(1)):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        cells = [c for c in cells if c and c not in {"◆", "◇"}]
        if len(cells) < 2:
            continue
        date, number = cells[0], cells[1]
        # Appendix rows such as "1 | 手数料の名称" have the same two-cell shape,
        # so only keep rows that really look like an enactment/amendment entry.
        if not HISTORY_DATE_RE.match(date) or not HISTORY_NUMBER_RE.match(number):
            continue
        history.append({"date": date, "number": number})
    return history


def parse_honbun(html: str, *, law_id: str, source_url: str, index_title: str = "") -> dict[str, Any]:
    lines, _scope = extract_lines(html)
    chapters = parse_chapters(_scope)
    resources = parse_resources(_scope, source_url)
    # Body chapter lines appear verbatim ("第2章 見出し"), while the table
    # of contents renders the same heading with a "(第N条―第M条)" range.
    # Match only the verbatim form so the TOC does not consume the counter.
    chapter_texts = {c["text"] for c in chapters}
    title_match = TITLE_TAG_RE.search(html)
    secondary_match = SECONDARY_TITLE_RE.search(html)
    title = ""
    if secondary_match:
        title = clean_title(secondary_match.group(1))
    elif title_match:
        title = clean_title(title_match.group(1))
    elif index_title:
        title = index_title.strip()

    date_number_matches = DATENUMBER_RE.findall(html)
    enacted_date = ""
    ordinance_number = ""
    effective_note = ""
    if date_number_matches:
        first = clean_title(date_number_matches[0])
        split = DATE_NUMBER_SPLIT_RE.match(first)
        if split:
            enacted_date, ordinance_number = split.group(1).strip(), split.group(2).strip()
        else:
            enacted_date = first
        if len(date_number_matches) > 1:
            effective_note = clean_title(date_number_matches[1])

    taikei_match = TAIKEI_RE.search(html)
    classification = clean_title(taikei_match.group(1)) if taikei_match else ""

    preamble: list[str] = []
    articles: list[dict[str, Any]] = []
    supplements: list[str] = []
    appendix_tables: list[str] = []
    appendix_styles: list[str] = []
    # A chapter and a section are tracked separately: entering a section used
    # to overwrite the chapter, so articles under any section lost theirs (#81).
    current_chapter: dict[str, str] | None = None
    current_section: dict[str, str] | None = None
    chapter_index = 0
    mode = "preamble"
    current_article: dict[str, Any] | None = None
    pending_heading = ""
    deferred_heading = ""
    structure_warnings: list[str] = []
    # Headings that exist only to say the provision was deleted. They belong to
    # navigation, not to an article body, and must not be reported as a lost
    # structure (issue #50).
    deleted_headings: list[str] = []

    def flush_article() -> None:
        nonlocal current_article
        if current_article is not None:
            current_article["text"] = "\n".join(current_article.pop("_lines")).strip()
            articles.append(current_article)
            current_article = None

    def absorb_deferred_heading() -> None:
        """Attach a held-back heading to the block that is ending.

        A pending heading must never cross a structural boundary. Before
        issue #61 it survived a chapter heading and landed on the next article,
        and the amendment note it came from was lost from the article body.
        """
        nonlocal deferred_heading
        if not deferred_heading:
            return
        if current_article is not None:
            current_article["_lines"].append(deferred_heading)
        elif mode == "supplement" and supplements:
            supplements[-1] = supplements[-1] + "\n" + deferred_heading
        elif mode == "appendix" and appendix_tables:
            appendix_tables[-1] = appendix_tables[-1] + "\n" + deferred_heading
        elif mode == "style" and appendix_styles:
            appendix_styles[-1] = appendix_styles[-1] + "\n" + deferred_heading
        deferred_heading = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if title and line in {title, f"○{title}"} and mode == "preamble" and not preamble:
            continue
        if enacted_date and line == enacted_date and mode == "preamble":
            continue
        if ordinance_number and line == ordinance_number and mode == "preamble":
            continue

        if (
            HEADING_LINE_RE.match(line)
            and not ITEM_RE.match(line)
            and mode in {"preamble", "article"}
            and not APPENDIX_TABLE_RE.match(line)
            and not is_amendment_note(line)
        ):
            # A heading line introduces the article that follows it. Keep it for
            # that article only and never append it to the article already being
            # parsed, which mixed the next article's heading into the previous
            # article text (issue #40).
            if current_article is None:
                pending_heading = line
            else:
                deferred_heading = line
            continue

        # A chapter/section heading line belongs to the structure, not to
        # the previous article (issue #50). Skip it and remember it for
        # the articles that follow.
        if line in chapter_texts:
            absorb_deferred_heading()
            if chapter_index < len(chapters):
                entry = chapters[chapter_index]
                chapter_index += 1
                if entry.get("kind") == "section":
                    current_section = entry
                else:
                    current_chapter = entry
                    current_section = None
            continue
        if CHAPTER_LINE_RE.match(line) or SECTION_LINE_RE.match(line):
            # Table-of-contents entries ("第2章 見出し(第N条―第M条)") are
            # navigation, not body text: skip them silently. A bare
            # chapter line that the body scope did not provide means the
            # structure was lost, so warn instead of mixing it into a
            # body paragraph (issue #50).
            absorb_deferred_heading()
            base, deleted = heading_identity(line)
            if any(line.startswith(text) for text in chapter_texts) or any(
                base == text or base.startswith(text) for text in chapter_texts
            ):
                continue
            if deleted:
                # 削除 sections have no body by definition, so this is not a
                # lost heading: keep it for navigation and stay quiet.
                deleted_headings.append(line)
                continue
            structure_warnings.append(f"chapter_heading_unstructured:{line[:30]}")
            continue

        article_match = ARTICLE_START_RE.match(line)
        # 附則・改正附則・別表・様式の中にも「第1条」形式の行がある。ここで
        # mode を戻すと附則の条文が本則 articles[] に混入し、同名ラベルが
        # 何十件も並ぶ (issue #95)。本文の条だけが article に切り替える。
        starts_article = (
            bool(article_match)
            and not SUPPLEMENT_RE.match(line)
            and mode not in {"supplement", "appendix", "style"}
        )
        if deferred_heading:
            if starts_article:
                if not pending_heading:
                    pending_heading = deferred_heading
            elif current_article is not None:
                current_article["_lines"].append(deferred_heading)
            elif not pending_heading:
                pending_heading = deferred_heading
            deferred_heading = ""

        if starts_article and article_match is not None:
            flush_article()
            mode = "article"
            number_text = article_match.group(1)
            branch = article_match.group(2)
            rest = article_match.group(3).strip()
            heading = pending_heading
            pending_heading = ""
            body_first = rest
            if rest.startswith(("(", "（")):
                inline_heading, inline_body = split_leading_heading(rest)
                if inline_heading:
                    heading, body_first = inline_heading, inline_body
            label = f"第{to_int(number_text)}条"
            if branch:
                label += "".join(f"の{to_int(part)}" for part in branch.split("の") if part)
            current_article = {
                "number": to_int(number_text),
                "branch": to_int(branch.split("の")[1]) if branch else None,
                "label": label,
                "heading": heading,
                "chapter": current_chapter["number"] if current_chapter else "",
                "chapter_title": current_chapter["title"] if current_chapter else "",
                "section": current_section["number"] if current_section else "",
                "section_title": current_section["title"] if current_section else "",
                "_lines": [line],
                "paragraphs": [],
            }
            if body_first:
                current_article["paragraphs"].append({"number": 1, "text": body_first, "items": []})
            continue

        if SUPPLEMENT_RE.match(line):
            absorb_deferred_heading()
            flush_article()
            mode = "supplement"
            supplements.append(line)
            continue

        if STYLE_SECTION_RE.match(line):
            # 様式第N号 is its own form. Concatenating it onto the last appendix
            # table corrupted that table's body (issue #61).
            absorb_deferred_heading()
            flush_article()
            mode = "style"
            appendix_styles.append(line)
            continue

        if APPENDIX_TABLE_RE.match(line):
            if APPENDIX_START_RE.match(line):
                absorb_deferred_heading()
                flush_article()
                mode = "appendix"
                appendix_tables.append(line)
                continue
            if mode in {"article", "supplement"} and APPENDIX_TITLE_HINT_RE.match(line):
                structure_warnings.append(f"appendix_marker_unparsed:{line[:30]}")

        if mode == "preamble":
            preamble.append(line)
        elif mode == "article" and current_article is not None:
            current_article["_lines"].append(line)
            paragraph_match = PARAGRAPH_RE.match(line)
            item_match = ITEM_RE.match(line)
            if item_match and current_article["paragraphs"]:
                current_article["paragraphs"][-1]["items"].append(
                    {"label": f"({to_int(item_match.group(1))})", "text": item_match.group(2).strip()}
                )
            elif paragraph_match and not line.startswith("第"):
                current_article["paragraphs"].append(
                    {"number": to_int(paragraph_match.group(1)), "text": paragraph_match.group(2).strip(), "items": []}
                )
            elif current_article["paragraphs"]:
                last = current_article["paragraphs"][-1]
                if last["items"]:
                    last["items"][-1]["text"] = (last["items"][-1]["text"] + " " + line).strip()
                else:
                    last["text"] = (last["text"] + " " + line).strip()
            else:
                current_article["paragraphs"].append({"number": 1, "text": line, "items": []})
        elif mode == "supplement":
            if supplements:
                supplements[-1] = supplements[-1] + "\n" + line if supplements[-1] != line else line
        elif mode == "appendix":
            if appendix_tables:
                appendix_tables[-1] = appendix_tables[-1] + "\n" + line
        elif mode == "style":
            if appendix_styles:
                appendix_styles[-1] = appendix_styles[-1] + "\n" + line

    flush_article()

    body_text = "\n".join(preamble)
    plain_text = "\n".join(lines)
    parse_warnings: list[str] = list(structure_warnings)
    # An ordinance can legitimately have no 第N条 in its main body: 抄 versions of
    # amendment ordinances consist only of 附則, and 別表-only ordinances carry
    # nothing but appendix tables. Only a law with no structured content at all
    # is a parse failure (issue #95 follow-up).
    if not articles and not body_text and not supplements and not appendix_tables:
        parse_warnings.append("no_articles_parsed")
    for parsed_article in articles:
        item_lines = [
            article_line
            for article_line in parsed_article["text"].splitlines()
            if ITEM_RE.match(article_line.strip())
        ]
        structured_items = sum(len(paragraph.get("items", [])) for paragraph in parsed_article["paragraphs"])
        if len(item_lines) != structured_items:
            parse_warnings.append(
                f"item_structure_mismatch:{parsed_article['label']}:text={len(item_lines)}:structured={structured_items}"
            )
    # Appendix tables that have a downloadable RTF/PNG but no body text are
    # not silently published as complete tables (issue #51).
    # Decided from the resolved mapping, not from "resources exist": a law whose
    # only resources are 様式 must not flag a one-line table heading that has no
    # file of its own (issue #61 review).
    for table, resource_index in zip(appendix_tables, build_resource_map(appendix_tables, resources)):
        if resource_index is not None and "\n" not in table.strip():
            parse_warnings.append(f"external_resource_only:{table[:30]}")
    history = parse_history(html)
    if not history and history_scope(html) is not None:
        parse_warnings.append("history_table_empty_or_unrecognized")
    return {
        "id": law_id,
        "title": title or index_title,
        "index_title": index_title,
        "enacted_date": enacted_date,
        "ordinance_number": ordinance_number,
        "effective_note": effective_note,
        "classification": classification,
        "source_url": source_url,
        "preamble": preamble,
        "body_text": body_text,
        "articles": articles,
        "article_count": len(articles),
        "supplements": supplements,
        "appendix_tables": appendix_tables,
        "appendix_styles": appendix_styles,
        "chapters": chapters,
        "deleted_headings": deleted_headings,
        "resources": resources,
        # Explicit table -> resource mapping. Consumers must use this instead of
        # law.resources[n - 1] (issue #61).
        "appendix_table_resource_index": build_resource_map(appendix_tables, resources),
        "history": history,
        "plain_text": plain_text,
        "text_sha256": hashlib.sha256(plain_text.encode("utf-8")).hexdigest(),
        "parse_warnings": parse_warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse one Higashimatsushima ordinance body HTML file.")
    parser.add_argument("html")
    parser.add_argument("--id", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    html = Path(args.html).read_text(encoding="utf-8", errors="replace")
    data = parse_honbun(html, law_id=args.id, source_url=args.url, index_title=args.title)
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        Path(args.output).write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
