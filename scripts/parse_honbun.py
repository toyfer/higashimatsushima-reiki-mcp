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
HISTORY_NUMBER_RE = re.compile(r"^(?:条例|規則|訓令|告示|指令|規程|要綱)第[0-9０-９]+号")
ARTICLE_START_RE = re.compile(r"^第([0-9０-９]+)条(?:の([0-9０-９]+))?\s*(.*)$")
HEADING_LINE_RE = re.compile(r"^[\(（].+[\)）]$")
SUPPLEMENT_RE = re.compile(r"^附\s*則")
APPENDIX_TABLE_RE = re.compile(r"^別表")
# 別表第1 and 別表(第2条関係) are both used by the city site; the second form
# was silently appended to the last supplement (issue #38).
APPENDIX_START_RE = re.compile(r"^別表(?:\s|第|[\(（]|$)")
PARAGRAPH_RE = re.compile(r"^([0-9０-９]+)\s+(.+)$")
ITEM_RE = re.compile(r"^[\(（]([0-9０-９]+)[\)）]\s*(.*)$")
SUBITEM_RE = re.compile(r"^([アイウエオカキクケコサシスセソタチツテト])\s*(.*)$")
DATE_NUMBER_SPLIT_RE = re.compile(r"^(.*?)\s+(.+)$")

ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def to_int(value: str) -> int:
    return int(value.translate(ZEN))


def clean_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\xa0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", value).strip().lstrip("○").strip()


def extract_lines(html: str) -> tuple[list[str], str]:
    match = PRIMARY_RE.search(html)
    scope = match.group(0) if match else html
    text = html_to_text(scope)
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
    mode = "preamble"
    current_article: dict[str, Any] | None = None
    pending_heading = ""
    deferred_heading = ""
    structure_warnings: list[str] = []

    def flush_article() -> None:
        nonlocal current_article
        if current_article is not None:
            current_article["text"] = "\n".join(current_article.pop("_lines")).strip()
            articles.append(current_article)
            current_article = None

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

        article_match = ARTICLE_START_RE.match(line)
        starts_article = bool(article_match) and not SUPPLEMENT_RE.match(line)
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
                label += f"の{to_int(branch)}"
            current_article = {
                "number": to_int(number_text),
                "branch": to_int(branch) if branch else None,
                "label": label,
                "heading": heading,
                "_lines": [line],
                "paragraphs": [],
            }
            if body_first:
                current_article["paragraphs"].append({"number": 1, "text": body_first, "items": []})
            continue

        if SUPPLEMENT_RE.match(line):
            flush_article()
            mode = "supplement"
            supplements.append(line)
            continue

        if APPENDIX_TABLE_RE.match(line):
            if APPENDIX_START_RE.match(line):
                flush_article()
                mode = "appendix"
                appendix_tables.append(line)
                continue
            if mode in {"article", "supplement"}:
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

    flush_article()

    body_text = "\n".join(preamble)
    plain_text = "\n".join(lines)
    parse_warnings: list[str] = list(structure_warnings)
    if not articles and not body_text:
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
