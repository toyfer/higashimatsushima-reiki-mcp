#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from daily_check import collect_from_taikei, extract_current_date, fetch_text
from parse_honbun import parse_honbun
from reiki_common import MENU_URL, USER_AGENT

SAFE_ID_RE = re.compile(r"^r\d+RG\d+$", re.I)


def load_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def public_law(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k != "plain_text"}


# Warnings that always mean the structured output cannot be trusted.
BLOCKING_WARNING_PREFIXES = ("item_structure_mismatch:", "no_articles_parsed")


def validate_built_api(api_root: Path, index: list[dict[str, Any]], data_version: str) -> list[str]:
    """Return a list of integrity problems in the built output (empty = valid)."""
    problems: list[str] = []
    laws_dir = api_root / "laws"
    for entry in index:
        law_id = str(entry.get("id", ""))
        path = laws_dir / f"{law_id}.json"
        if not path.exists():
            problems.append(f"missing_law_file:{law_id}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"unreadable_law_file:{law_id}:{exc!r}")
            continue
        for field in ("id", "title", "source_url", "articles", "text_sha256"):
            if field not in data:
                problems.append(f"missing_field:{law_id}:{field}")
        if data.get("id") != law_id:
            problems.append(f"id_mismatch:{law_id}")
        articles = data.get("articles")
        if not isinstance(articles, list):
            problems.append(f"bad_articles_type:{law_id}")
        else:
            for article in articles:
                if not isinstance(article, dict):
                    problems.append(f"bad_article_entry:{law_id}")
                    continue
                label = article.get("label", "?")
                paragraphs = article.get("paragraphs", [])
                if not isinstance(paragraphs, list):
                    problems.append(f"bad_paragraphs_type:{law_id}:{label}")
                    continue
                for paragraph in paragraphs:
                    if not isinstance(paragraph, dict):
                        problems.append(f"bad_paragraph_entry:{law_id}:{label}")
                        continue
                    if "number" not in paragraph or "text" not in paragraph:
                        problems.append(f"bad_paragraph:{law_id}:{label}")
                    items = paragraph.get("items", [])
                    if not isinstance(items, list):
                        problems.append(f"bad_items_type:{law_id}:{label}")
                        continue
                    for item in items:
                        if not isinstance(item, dict) or "label" not in item or "text" not in item:
                            problems.append(f"bad_item:{law_id}:{label}")
    index_path = laws_dir / "index.json"
    try:
        built_index = json.loads(index_path.read_text(encoding="utf-8"))
        if built_index.get("data_version") != data_version:
            problems.append("index_data_version_mismatch")
        built_laws = built_index.get("laws")
        if not isinstance(built_laws, list):
            problems.append("index_laws_type_mismatch")
        elif len(built_laws) != len(index):
            problems.append("index_count_mismatch")
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"unreadable_index:{exc!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GitHub Pages static API JSON for Higashimatsushima ordinances.")
    parser.add_argument("--status", default="data/status/latest.json")
    parser.add_argument("--out", default="site")
    parser.add_argument("--api-base", default="api")
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only-id", action="append", default=[])
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    status = load_status(Path(args.status))
    laws = status.get("laws") or []
    if not laws:
        print("No laws in status file. Run daily_check.py --mode collect first.", file=sys.stderr)
        return 2
    total_count = len(status.get("laws") or [])
    if args.only_id:
        wanted = set(args.only_id)
        laws = [law for law in laws if law.get("id") in wanted]
    if args.limit:
        laws = laws[: args.limit]

    try:
        menu_html, menu_hash = fetch_text(MENU_URL)
        current_date = extract_current_date(menu_html)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"WARNING: menu fetch failed: {exc!r}", file=sys.stderr)
        menu_hash = str(status.get("menu_sha256", ""))
        current_date = str(status.get("current_date", ""))

    out_root = Path(args.out)
    api_root = out_root / args.api_base
    laws_dir = api_root / "laws"
    laws_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    selected_count = len(laws)
    is_full_build = not args.limit and not args.only_id
    index: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    warning_count = 0
    warnings_by_law: list[dict[str, Any]] = []

    for pos, law in enumerate(laws, start=1):
        law_id = str(law.get("id", ""))
        url = str(law.get("url", ""))
        title_hint = str(law.get("title", ""))
        if not SAFE_ID_RE.match(law_id) or not url:
            failures.append({"id": law_id, "url": url, "error": "invalid_status_entry"})
            print(f"WARNING: {law_id} invalid_status_entry", file=sys.stderr)
            if args.fail_on_error:
                return 3
            continue
        try:
            html, _digest = fetch_text(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failures.append({"id": law_id, "url": url, "error": repr(exc)})
            if args.fail_on_error:
                return 3
            continue
        data = parse_honbun(html, law_id=law_id, source_url=url, index_title=title_hint)
        law_warnings = list(data.get("parse_warnings", []))
        if law_warnings:
            warning_count += len(law_warnings)
            warnings_by_law.append({"id": law_id, "warnings": law_warnings})
        blocking = [w for w in law_warnings if w.startswith(BLOCKING_WARNING_PREFIXES)]
        if blocking:
            failures.append({"id": law_id, "url": url, "error": "; ".join(blocking)})
            print(f"WARNING: {law_id} structural parse mismatch: {'; '.join(blocking)}", file=sys.stderr)
            if args.fail_on_error:
                return 3
            continue
        if law_warnings and args.fail_on_error:
            failures.append({"id": law_id, "url": url, "error": "; ".join(law_warnings)})
            print(f"WARNING: {law_id} parse warnings treated as failures: {'; '.join(law_warnings)}", file=sys.stderr)
            return 3
        data["fetched_at_utc"] = generated_at
        data["menu_sha256"] = menu_hash
        data["content_current_date"] = current_date
        dump_json(laws_dir / f"{law_id}.json", public_law(data))
        first_article = data["articles"][0]["label"] if data["articles"] else ""
        index.append(
            {
                "id": law_id,
                "title": data["title"],
                "enacted_date": data["enacted_date"],
                "ordinance_number": data["ordinance_number"],
                "classification": data["classification"],
                "body_text": data.get("body_text", "") if not data["articles"] else "",
                "article_count": data["article_count"],
                "first_article": first_article,
                "source_url": url,
                "api_path": f"{args.api_base}/laws/{law_id}.json",
                "text_sha256": data["text_sha256"],
                "parse_warnings": data["parse_warnings"],
            }
        )
        print(f"[{pos}/{len(laws)}] {law_id} {data['title']} articles={data['article_count']}")
        if args.delay > 0:
            time.sleep(args.delay)

    version_source = f"{generated_at}:{current_date}:{len(index)}:{menu_hash}"
    version = hashlib.sha256(version_source.encode("utf-8")).hexdigest()[:16]
    meta = {
        "name": "Higashimatsushima City ordinances static API",
        "generated_at_utc": generated_at,
        "content_current_date": current_date,
        "menu_url": MENU_URL,
        "menu_sha256": menu_hash,
        "data_version": version,
        "law_count": len(index),
        "failure_count": len(failures),
        "failures": failures,
    }
    meta["selected_count"] = selected_count
    meta["expected_count"] = total_count
    meta["warning_count"] = warning_count
    meta["warnings"] = warnings_by_law
    dump_json(api_root / "meta.json", meta)
    dump_json(api_root / "laws" / "index.json", {"data_version": version, "generated_at_utc": generated_at, "laws": index})
    dump_json(api_root / "search" / "title-index.json", {"data_version": version, "laws": [{"id": x["id"], "title": x["title"], "ordinance_number": x["ordinance_number"]} for x in index]})
    validation_problems = validate_built_api(api_root, index, version)
    count_matches = len(index) + len(failures) == selected_count
    full_build_complete = (not is_full_build) or (len(index) == selected_count and not failures)
    healthy = bool(index) and not failures and not validation_problems and count_matches and full_build_complete
    health = {
        "ok": healthy and len(index) == total_count,
        "law_count": len(index),
        "selected_count": selected_count,
        "expected_count": total_count,
        "failure_count": len(failures),
        "warning_count": warning_count,
        "validation_problems": validation_problems,
        "data_version": version,
    }
    dump_json(api_root / "health.json", health)

    (out_root / ".nojekyll").write_text("", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if validation_problems:
        print(f"ERROR: built API failed validation: {validation_problems}", file=sys.stderr)
        return 5
    if args.fail_on_error and failures:
        return 3
    if is_full_build and (failures or len(index) != selected_count):
        print(f"ERROR: full build incomplete: generated {len(index)}/{selected_count} with {len(failures)} failure(s)", file=sys.stderr)
        return 5
    return 0 if index else 4


if __name__ == "__main__":
    raise SystemExit(main())
