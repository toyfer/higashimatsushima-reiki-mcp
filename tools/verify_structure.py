"""Compare freshly parsed ordinance HTML with the published JSON.

A rebuild can change article counts, chapter/section assignment or the number of
supplements without failing any existing test, because those values are data
rather than assertions. This tool re-parses a sample straight from the city site
and reports every difference against the published API, so a rebuild can be
checked against the source instead of against the previous build.

Usage:
    python tools/verify_structure.py --sample 10
    python tools/verify_structure.py --ids r122RG00000066 r122RG00000093

Exit code is 0 when every law matches on article count and chapter structure,
including the expected supplement difference caused by table-of-contents rows in
older builds (issue #81). A mismatch prints the law and both values.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from parse_honbun import parse_honbun

DEFAULT_API_BASE = "https://toyfer.github.io/higashimatsushima-reiki-mcp"
USER_AGENT = "higashimatsushima-reiki-structure-verifier/1.0"
TOC_SUPPLEMENT_RE = re.compile(r'class="toc_item-supplement"')


def fetch_text(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def fetch_json(url: str) -> dict:
    return json.loads(fetch_text(url))


def compare(law_id: str, html: str, published: dict, source_url: str = "") -> dict:
    """Parse ``html`` and diff it against the published law document."""
    law = parse_honbun(html, law_id=law_id, source_url=source_url)
    toc_supplements = len(TOC_SUPPLEMENT_RE.findall(html))
    published_supplements = len(published.get("supplements") or [])
    parsed_supplements = len(law["supplements"])
    return {
        "law_id": law_id,
        "title": law["title"],
        "articles": law["article_count"],
        "published_articles": published.get("article_count"),
        "chapters": len(law["chapters"]),
        "published_chapters": len(published.get("chapters") or []),
        "supplements": parsed_supplements,
        "published_supplements": published_supplements,
        "toc_supplements": toc_supplements,
        "unstructured_warnings": [
            warning for warning in law["parse_warnings"] if warning.startswith("chapter_heading_unstructured")
        ],
        "first_article": (law["articles"][0] if law["articles"] else {}),
    }


def problems(row: dict) -> list[str]:
    found = []
    if row["articles"] != row["published_articles"]:
        found.append(f"articles {row['articles']} != published {row['published_articles']}")
    if row["chapters"] != row["published_chapters"]:
        found.append(f"chapters {row['chapters']} != published {row['published_chapters']}")
    # Builds made before issue #81 counted the table-of-contents 附則 row as a
    # supplement, so the published count may legitimately be that much larger.
    expected_published = row["supplements"] + row["toc_supplements"]
    if row["published_supplements"] not in (row["supplements"], expected_published):
        found.append(
            f"supplements {row['supplements']} (published {row['published_supplements']}, "
            f"toc rows {row['toc_supplements']})"
        )
    if row["unstructured_warnings"]:
        found.append(f"unstructured headings {row['unstructured_warnings'][:2]}")
    return found


def sample_laws(api_base: str, sample: int, seed: int) -> list[dict]:
    index = fetch_json(f"{api_base}/api/laws/index.json")
    laws = [law for law in index.get("laws") or [] if law.get("source_url")]
    random.seed(seed)
    if sample >= len(laws):
        return laws
    return random.sample(laws, sample)


def find_law(api_base: str, law_id: str) -> dict:
    index = fetch_json(f"{api_base}/api/laws/index.json")
    for law in index.get("laws") or []:
        if law.get("id") == law_id:
            return law
    return {"id": law_id, "source_url": f"https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_honbun/{law_id}.html"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--sample", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261113)
    parser.add_argument("--ids", nargs="*", default=[])
    args = parser.parse_args(argv)

    targets = [find_law(args.api_base, law_id) for law_id in args.ids]
    if not targets:
        targets = sample_laws(args.api_base, args.sample, args.seed)

    failures = 0
    print(f"{'law':<18}{'art':>5}{'pub':>5}{'ch':>4}{'pubch':>6}{'sup':>5}{'pubsup':>7}{'toc':>4}  first article")
    for target in targets:
        law_id = target["id"]
        source_url = target.get("source_url") or ""
        try:
            html = fetch_text(source_url)
            published = fetch_json(f"{args.api_base}/api/laws/{law_id}.json")
        except Exception as exc:  # network failures are reported, not hidden
            failures += 1
            print(f"{law_id:<18} error {exc!r}")
            continue
        row = compare(law_id, html, published, source_url)
        first = row["first_article"]
        print(
            f"{law_id:<18}{row['articles']:>5}{row['published_articles']:>5}{row['chapters']:>4}"
            f"{row['published_chapters']:>6}{row['supplements']:>5}{row['published_supplements']:>7}"
            f"{row['toc_supplements']:>4}  {first.get('label', '-')} {first.get('chapter', '')}/{first.get('section', '')}"
        )
        found = problems(row)
        if found:
            failures += 1
            for problem in found:
                print(f"  PROBLEM {problem}")
    print("OK" if failures == 0 else f"{failures} law(s) differ from the published API")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
