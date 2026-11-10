#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from search_index import build_search_index


def laws_from_site(site_api: Path) -> list[dict[str, Any]]:
    index_path = site_api / "laws" / "index.json"
    laws: list[dict[str, Any]] = []
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in index.get("laws") or []:
            path = site_api / "laws" / f"{entry.get('id')}.json"
            if path.exists():
                laws.append(json.loads(path.read_text(encoding="utf-8")))
        return laws
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((site_api / "laws").glob("*.json")) if path.name != "index.json"]


def main() -> int:
    site_api = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("site/api")
    laws = laws_from_site(site_api)
    started = time.perf_counter()
    builder = build_search_index(laws)
    built = builder.build(data_version="measure", generated_at_utc="measure")
    elapsed = time.perf_counter() - started
    with tempfile.TemporaryDirectory() as tmp:
        manifest = builder.write(Path(tmp) / "search", data_version="measure", generated_at_utc="measure")
        total_bytes = sum(path.stat().st_size for path in (Path(tmp) / "search").glob("*.json"))
    posting_terms = sum(len(data.get("terms") or {}) for data in built["postings"].values())
    posting_entries = sum(len(v) for data in built["postings"].values() for v in (data.get("terms") or {}).values())
    print(json.dumps({
        "laws": len(laws), "chunks": manifest["chunk_count"], "posting_terms": posting_terms,
        "posting_entries": posting_entries, "files": 1 + len(manifest["files"]["chunks"]) + len(manifest["files"]["postings"]),
        "total_bytes": total_bytes, "seconds": round(elapsed, 3),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
