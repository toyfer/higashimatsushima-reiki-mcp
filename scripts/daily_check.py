#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

MENU_URL = "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_menu.html"
TAIKEI_URL = "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_taikei/taikei_default.html"
USER_AGENT = "higashimatsushima-reiki-mcp/0.1 (+daily public-page change check)"
CURRENT_RE = re.compile(r"内容現在\s*（?([^\s<）)]+(?:年|/)[^\s<）)]*)")
HONBUN_RE = re.compile(r"reiki_honbun/(r\d+RG\d+\.html)", re.IGNORECASE)
TAIKEI_PAGE_RE = re.compile(r"r_taikei_[0-9_]+\.html$", re.IGNORECASE)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def fetch_text(url: str, timeout: int = 30) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
        charset = res.headers.get_content_charset() or "utf-8"
    text = raw.decode(charset, errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return text, digest


def extract_current_date(html: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = plain.replace("&nbsp;", " ")
    plain = re.sub(r"\s+", " ", plain)
    match = CURRENT_RE.search(plain)
    return match.group(1).strip() if match else ""


def extract_honbun_links(page_url: str, html: str) -> list[dict[str, str]]:
    parser = LinkParser()
    parser.feed(html)
    seen: dict[str, dict[str, str]] = {}
    for href, label in parser.links:
        filename_match = HONBUN_RE.search(href)
        if not filename_match:
            continue
        filename = filename_match.group(1)
        law_id = re.sub(r"\.html$", "", filename, flags=re.IGNORECASE)
        seen[law_id] = {
            "id": law_id,
            "title": label,
            "url": urljoin(page_url, href),
            "source_page": page_url,
        }
    return [seen[key] for key in sorted(seen)]


def collect_from_taikei(max_pages: int, delay_seconds: float) -> dict[str, object]:
    queue = [TAIKEI_URL]
    visited: set[str] = set()
    laws: dict[str, dict[str, str]] = {}
    page_errors: list[dict[str, str]] = []

    while queue and len(visited) < max_pages:
        page_url = queue.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)
        try:
            html, _ = fetch_text(page_url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            page_errors.append({"url": page_url, "error": repr(exc)})
            continue

        for law in extract_honbun_links(page_url, html):
            laws[law["id"]] = law

        parser = LinkParser()
        parser.feed(html)
        for href, _label in parser.links:
            absolute = urljoin(page_url, href)
            filename = absolute.rsplit("/", 1)[-1]
            if "/reiki_taikei/" in absolute and TAIKEI_PAGE_RE.match(filename):
                if absolute not in visited and absolute not in queue:
                    queue.append(absolute)

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return {
        "visited_pages": sorted(visited),
        "visited_page_count": len(visited),
        "laws": [laws[key] for key in sorted(laws)],
        "law_count": len(laws),
        "page_errors": page_errors,
    }


def set_github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Higashimatsushima ordinance pages for changes.")
    parser.add_argument("--mode", choices=("check", "collect"), default="check")
    parser.add_argument("--menu-url", default=MENU_URL)
    parser.add_argument("--previous", default="data/status/latest.json")
    parser.add_argument("--output", default="data/status/latest.json")
    parser.add_argument("--summary", default="data/status/latest-summary.md")
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--force-collect", action="store_true")
    args = parser.parse_args()

    checked_at = datetime.now(timezone.utc).isoformat()
    previous: dict[str, object] = {}
    previous_path = Path(args.previous)
    if previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}

    try:
        menu_html, menu_hash = fetch_text(args.menu_url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"ERROR: failed to fetch menu: {exc!r}", file=sys.stderr)
        set_github_output("status", "fetch_failed")
        return 2

    current_date = extract_current_date(menu_html)
    previous_hash = str(previous.get("menu_sha256", ""))
    previous_date = str(previous.get("current_date", ""))
    previous_law_count = previous.get("law_count")

    changed = bool(args.force_collect or not previous or menu_hash != previous_hash or current_date != previous_date)
    should_collect = args.mode == "collect" or changed

    result: dict[str, object] = {
        "checked_at_utc": checked_at,
        "menu_url": args.menu_url,
        "menu_sha256": menu_hash,
        "previous_menu_sha256": previous_hash,
        "current_date": current_date,
        "previous_current_date": previous_date,
        "changed": changed,
        "mode": args.mode,
        "law_count": previous_law_count,
        "laws": previous.get("laws", []),
        "visited_page_count": previous.get("visited_page_count", 0),
        "page_errors": [],
    }

    collection: dict[str, object] | None = None
    if should_collect:
        collection = collect_from_taikei(args.max_pages, args.delay)
        result.update(
            {
                "law_count": collection["law_count"],
                "laws": collection["laws"],
                "visited_page_count": collection["visited_page_count"],
                "visited_pages": collection["visited_pages"],
                "page_errors": collection["page_errors"],
            }
        )
        if collection["page_errors"]:
            print(f"ERROR: {len(collection['page_errors'])} page(s) failed", file=sys.stderr)
            set_github_output("status", "collect_failed")
            return 3
        if int(collection["law_count"]) <= 0:
            print("ERROR: no ordinance links found", file=sys.stderr)
            set_github_output("status", "empty_index")
            return 4
        if isinstance(previous_law_count, int) and previous_law_count > 0:
            drop_ratio = (previous_law_count - int(collection["law_count"])) / previous_law_count
            if drop_ratio > 0.10:
                print(
                    f"ERROR: law count dropped too much: {previous_law_count} -> {collection['law_count']}",
                    file=sys.stderr,
                )
                set_github_output("status", "suspicious_drop")
                return 5

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary_lines = [
        "## Higashimatsushima ordinance daily check",
        "",
        f"- Checked at UTC: `{checked_at}`",
        f"- Menu: {args.menu_url}",
        f"- Current date on site: `{current_date or 'unknown'}`",
        f"- Changed: `{str(changed).lower()}`",
        f"- Mode: `{args.mode}`",
        f"- Ordinances indexed: `{result.get('law_count')}`",
        f"- Visited index pages: `{result.get('visited_page_count')}`",
    ]
    if collection is not None:
        summary_lines.append("- Index pages were crawled in this run.")
    else:
        summary_lines.append("- Index pages were not crawled because the menu page did not change.")
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(summary_lines) + "\n")

    set_github_output("status", "changed" if changed else "unchanged")
    set_github_output("changed", str(changed).lower())
    set_github_output("current_date", current_date)
    set_github_output("law_count", str(result.get("law_count") or ""))
    print("\n".join(summary_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
