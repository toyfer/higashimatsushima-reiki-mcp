#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

CHUNK_SHARD_SIZE = 500
LENGTH_NORM_ALPHA = 0.25
APPENDIX_BOOST = 1.5
POSTING_SHARD_COUNT = 16
MAX_POSTINGS_PER_TERM = 50
MAX_POSTINGS_PER_LAW_PER_TERM = 3
SNIPPET_CHARS = 280
LONG_ARTICLE_CHARS = 1200

_WS_RE = re.compile(r"\s+")


def fnv1a_32(value: str) -> int:
    result = 2166136261
    for char in value:
        result ^= ord(char)
        result = (result * 16777619) & 0xFFFFFFFF
    return result


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return "".join(char for char in normalized if char.isalnum())


def text_bigrams(value: str) -> list[str]:
    normalized = normalize_text(value)
    if len(normalized) < 2:
        return [normalized] if normalized else []
    return [normalized[index : index + 2] for index in range(len(normalized) - 1)]


def _collapse(value: str) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _paragraph_text(paragraph: dict[str, Any]) -> str:
    parts = [str(paragraph.get("text") or "")]
    for item in paragraph.get("items") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("text") or ""))
    return _collapse(" ".join(parts))


def _article_text(article: dict[str, Any]) -> str:
    text = _collapse(str(article.get("text") or ""))
    if text:
        return text
    return _collapse(" ".join(_paragraph_text(p) for p in article.get("paragraphs") or [] if isinstance(p, dict)))


def _preamble_text(law: dict[str, Any]) -> str:
    body_text = _collapse(str(law.get("body_text") or ""))
    if body_text:
        return body_text
    preamble = law.get("preamble") or []
    skip = {_collapse(str(law.get(key) or "")) for key in ("enacted_date", "ordinance_number", "title")}
    skip.discard("")
    if isinstance(preamble, list):
        kept = [_collapse(str(part)) for part in preamble]
        kept = [part for part in kept if part and part not in skip]
        text = _collapse(" ".join(kept))
    elif isinstance(preamble, str):
        text = _collapse(preamble)
    else:
        text = ""
    # When articles exist, preamble lines are mostly title/date/number
    # boilerplate; only keep a substantive purpose/scope statement.
    if (law.get("articles") or []) and len(text) < 20:
        return ""
    return text


def chunk_law(law: dict[str, Any]) -> list[dict[str, Any]]:
    law_id = str(law.get("id") or "")
    title = str(law.get("title") or "")
    source_url = str(law.get("source_url") or "")
    chunks: list[dict[str, Any]] = []

    def add(label: str, heading: str, body: str, kind: str) -> None:
        collapsed = _collapse(body)
        if not collapsed:
            return
        chunks.append(
            {
                "law_id": law_id,
                "title": title,
                "label": label,
                "heading": heading,
                "kind": kind,
                "source_url": source_url,
                "snippet": collapsed[:SNIPPET_CHARS],
                # Full body text, kept so the Worker can verify a phrase and
                # build a query-aware window instead of trusting bigram
                # coincidence alone (issues #49, #52).
                "text": collapsed,
                "search_text": _collapse(" ".join([title, label, heading, collapsed])),
            }
        )

    preamble = _preamble_text(law)
    if preamble:
        add("前文", "", preamble, "preamble")
    for article in law.get("articles") or []:
        if not isinstance(article, dict):
            continue
        label = str(article.get("label") or "")
        heading = str(article.get("heading") or "")
        body = _article_text(article)
        paragraphs = [p for p in article.get("paragraphs") or [] if isinstance(p, dict)]
        if not paragraphs:
            add(label, heading, body, "article")
            continue
        if len(body) <= LONG_ARTICLE_CHARS:
            add(label, heading, body, "article")
            continue
        for paragraph in paragraphs:
            number = paragraph.get("number", "")
            paragraph_label = f"{label} 第{number}項" if label and number != "" else label
            add(paragraph_label, heading, _paragraph_text(paragraph), "article_paragraph")
    for position, table in enumerate(law.get("appendix_tables") or [], start=1):
        raw_body = str(table)
        lines = raw_body.splitlines()
        heading_line = lines[0].strip()[:40] if lines else ""
        label = heading_line or f"別表{position}"
        groups: dict[str, list[str]] = {}
        for line in lines[1:]:
            collapsed_line = _collapse(line)
            if not collapsed_line:
                continue
            groups.setdefault(label, []).append(collapsed_line)
        if not groups:
            add(label, "", raw_body, "appendix_table")
            continue
        for group_label, rows in groups.items():
            add(group_label, "", " ".join(rows), "appendix_table")
    for position, supplement in enumerate(law.get("supplements") or [], start=1):
        label = f"附則{position}" if len(law.get("supplements") or []) > 1 else "附則"
        add(label, "", str(supplement), "supplement")
    return chunks


class SearchIndexBuilder:
    def __init__(self) -> None:
        self._chunks: list[dict[str, Any]] = []
        self._counts: list[Counter[str]] = []
        self._law_ids: set[str] = set()

    def add_law(self, law: dict[str, Any]) -> None:
        for chunk in chunk_law(law):
            counts = Counter(text_bigrams(chunk["search_text"]))
            if not counts:
                continue
            if chunk["law_id"]:
                self._law_ids.add(chunk["law_id"])
            self._chunks.append(chunk)
            self._counts.append(counts)

    def add_laws(self, laws: Iterable[dict[str, Any]]) -> None:
        for law in laws:
            self.add_law(law)

    def build(self, *, data_version: str, generated_at_utc: str) -> dict[str, Any]:
        total = len(self._chunks)
        df: Counter[str] = Counter()
        for counts in self._counts:
            df.update(counts.keys())
        idf = {term: math.log(1.0 + total / (1.0 + count)) for term, count in df.items()}
        # Mild document-length normalization: long appendix tables must not win
        # on raw digit/term repetition alone, while amount tables that define a
        # rule stay competitive because their matched terms keep high counts.
        # Appendix tables carry the operative thresholds/amounts in municipal
        # regulations, so they get a fixed boost against the length penalty;
        # full-corpus checks keep salary-style tables out of the top ranks
        # while decision-threshold tables stay reachable.
        lengths = [sum(counts.values()) for counts in self._counts]
        raw: dict[str, list[list[Any]]] = {}
        for index, counts in enumerate(self._counts):
            norm = max(lengths[index], 1) ** LENGTH_NORM_ALPHA
            boost = APPENDIX_BOOST if self._chunks[index].get("kind") == "appendix_table" else 1.0
            for term, count in counts.items():
                raw.setdefault(term, []).append(
                    [index, round((1.0 + math.log(count)) * idf[term] * boost / norm, 4)]
                )
        postings: dict[str, list[list[Any]]] = {}
        for term, entries in raw.items():
            entries.sort(key=lambda e: (-e[1], e[0]))
            per_law: Counter[str] = Counter()
            kept: list[list[Any]] = []
            for index, score in entries:
                law_id = str(self._chunks[index].get("law_id") or "")
                if law_id and per_law[law_id] >= MAX_POSTINGS_PER_LAW_PER_TERM:
                    continue
                kept.append([index, score])
                if law_id:
                    per_law[law_id] += 1
                if len(kept) >= MAX_POSTINGS_PER_TERM:
                    break
            postings[term] = kept
        chunk_files: dict[str, Any] = {}
        for start in range(0, total, CHUNK_SHARD_SIZE):
            rows = []
            for index in range(start, min(start + CHUNK_SHARD_SIZE, total)):
                chunk = self._chunks[index]
                rows.append(
                    {
                        "i": index,
                        "law_id": chunk["law_id"],
                        "title": chunk["title"],
                        "label": chunk["label"],
                        "heading": chunk["heading"],
                        "kind": chunk.get("kind", ""),
                        "source_url": chunk.get("source_url", ""),
                        "snippet": chunk["snippet"],
                        "text": chunk.get("text", chunk["snippet"]),
                    }
                )
            chunk_files[f"chunks-{start // CHUNK_SHARD_SIZE:03d}.json"] = {"data_version": data_version, "chunks": rows}
        sharded: dict[int, dict[str, list[list[Any]]]] = {}
        for term in sorted(postings):
            sharded.setdefault(fnv1a_32(term) % POSTING_SHARD_COUNT, {})[term] = postings[term]
        posting_files = {
            f"postings-{shard:02d}.json": {"data_version": data_version, "terms": sharded.get(shard, {})}
            for shard in range(POSTING_SHARD_COUNT)
        }
        posting_terms = len(postings)
        posting_entries = sum(len(entries) for entries in postings.values())
        manifest = {
            "version": 1,
            "kind": "bigram-tfidf",
            "data_version": data_version,
            "generated_at_utc": generated_at_utc,
            "law_count": len(self._law_ids),
            "chunk_count": total,
            "chunk_shard_size": CHUNK_SHARD_SIZE,
            "length_norm_alpha": LENGTH_NORM_ALPHA,
            "appendix_boost": APPENDIX_BOOST,
            "posting_shards": POSTING_SHARD_COUNT,
            "max_postings_per_term": MAX_POSTINGS_PER_TERM,
            "max_postings_per_law_per_term": MAX_POSTINGS_PER_LAW_PER_TERM,
            # Vocabulary and total posting sizes, so index growth can be
            # monitored (raising these caps would enlarge the shards quickly).
            "posting_terms": posting_terms,
            "posting_entries": posting_entries,
            "files": {"chunks": sorted(chunk_files), "postings": sorted(posting_files)},
        }
        return {"manifest": manifest, "chunks": chunk_files, "postings": posting_files}

    def write(self, search_root: Path, *, data_version: str, generated_at_utc: str) -> dict[str, Any]:
        built = self.build(data_version=data_version, generated_at_utc=generated_at_utc)
        search_root.mkdir(parents=True, exist_ok=True)
        for group in ("chunks", "postings"):
            for name, data in built[group].items():
                (search_root / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        manifest = built["manifest"]
        (search_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest


def build_search_index(laws: Iterable[dict[str, Any]]) -> SearchIndexBuilder:
    builder = SearchIndexBuilder()
    builder.add_laws(laws)
    return builder
