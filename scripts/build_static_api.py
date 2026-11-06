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
    index: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for pos, law in enumerate(laws, start=1):
        law_id = str(law.get("id", ""))
        url = str(law.get("url", ""))
        title_hint = str(law.get("title", ""))
        if not SAFE_ID_RE.match(law_id) or not url:
            failures.append({"id": law_id, "url": url, "error": "invalid_status_entry"})
            continue
        try:
            html, _digest = fetch_text(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failures.append({"id": law_id, "url": url, "error": repr(exc)})
            if args.fail_on_error:
                return 3
            continue
        data = parse_honbun(html, law_id=law_id, source_url=url, index_title=title_hint)
        blocking = [w for w in data.get("parse_warnings", []) if w.startswith("item_structure_mismatch:")]
        if blocking:
            failures.append({"id": law_id, "url": url, "error": "; ".join(blocking)})
            print(f"WARNING: {law_id} structural parse mismatch: {'; '.join(blocking)}", file=sys.stderr)
            if args.fail_on_error:
                return 3
            continue
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
    dump_json(api_root / "meta.json", meta)
    dump_json(api_root / "laws" / "index.json", {"data_version": version, "generated_at_utc": generated_at, "laws": index})
    dump_json(api_root / "search" / "title-index.json", {"data_version": version, "laws": [{"id": x["id"], "title": x["title"], "ordinance_number": x["ordinance_number"]} for x in index]})
    dump_json(api_root / "health.json", {"ok": len(index) > 0, "law_count": len(index), "failure_count": len(failures), "data_version": version})

    (out_root / ".nojekyll").write_text("", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0 if index else 4


if __name__ == "__main__":
    raise SystemExit(main())
