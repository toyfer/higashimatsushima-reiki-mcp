#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

VECTOR_DIM = 128
CHUNK_SHARD_SIZE = 250
POSTING_SHARD_COUNT = 16
MAX_POSTINGS_PER_TERM = 50
MAX_DF_RATIO = 0.5
SNIPPET_CHARS = 280

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


def _article_text(article: dict[str, Any]) -> str:
    text = _collapse(str(article.get("text") or ""))
    if text:
        return text
    parts: list[str] = []
    for paragraph in article.get("paragraphs") or []:
        if not isinstance(paragraph, dict):
            continue
        parts.append(str(paragraph.get("text") or ""))
        for item in paragraph.get("items") or []:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
    return _collapse(" ".join(parts))


def chunk_law(law: dict[str, Any]) -> list[dict[str, str]]:
    law_id = str(law.get("id") or "")
    title = str(law.get("title") or "")
    chunks: list[dict[str, str]] = []
    for article in law.get("articles") or []:
        if not isinstance(article, dict):
            continue
        label = str(article.get("label") or "")
        heading = str(article.get("heading") or "")
        body = _article_text(article)
        if not body and not heading:
            continue
        search_text = _collapse(" ".join([title, label, heading, body]))
        chunks.append(
            {
                "law_id": law_id,
                "title": title,
                "label": label,
                "heading": heading,
                "snippet": body[:SNIPPET_CHARS],
                "search_text": search_text,
            }
        )
    for position, table in enumerate(law.get("appendix_tables") or [], start=1):
        body = _collapse(str(table))
        if not body:
            continue
        label = body.splitlines()[0][:40] if body else f"別表{position}"
        chunks.append(
            {
                "law_id": law_id,
                "title": title,
                "label": label,
                "heading": "",
                "snippet": body[:SNIPPET_CHARS],
                "search_text": _collapse(" ".join([title, label, body])),
            }
        )
    for position, supplement in enumerate(law.get("supplements") or [], start=1):
        body = _collapse(str(supplement))
        if not body:
            continue
        chunks.append(
            {
                "law_id": law_id,
                "title": title,
                "label": f"附則{position}" if len(law.get("supplements") or []) > 1 else "附則",
                "heading": "",
                "snippet": body[:SNIPPET_CHARS],
                "search_text": _collapse(" ".join([title, "附則", body])),
            }
        )
    return chunks


def dense_vector(counts: Counter[str], dim: int = VECTOR_DIM) -> str:
    vector = [0.0] * dim
    for term, count in counts.items():
        digest = fnv1a_32(term)
        weight = 1.0 + math.log(count)
        vector[digest % dim] += weight if (digest >> 8) % 2 == 0 else -weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    quantized = bytes(max(-128, min(127, round(value * 127))) & 0xFF for value in vector)
    return base64.b64encode(quantized).decode("ascii")


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
        document_frequency: Counter[str] = Counter()
        for counts in self._counts:
            document_frequency.update(counts.keys())
        max_df = max(1, int(total * MAX_DF_RATIO)) if total else 1
        postings: dict[str, list[list[Any]]] = {}
        for term, df in document_frequency.items():
            if total > 20 and df > max_df:
                continue
            idf = math.log(1.0 + total / (1.0 + df))
            entries: list[list[Any]] = []
            for index, counts in enumerate(self._counts):
                count = counts.get(term)
                if count:
                    entries.append([index, round((1.0 + math.log(count)) * idf, 4)])
            entries.sort(key=lambda entry: (-entry[1], entry[0]))
            postings[term] = entries[:MAX_POSTINGS_PER_TERM]
        chunk_files: dict[str, Any] = {}
        for start in range(0, total, CHUNK_SHARD_SIZE):
            name = f"chunks-{start // CHUNK_SHARD_SIZE:03d}.json"
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
                        "snippet": chunk["snippet"],
                        "v": dense_vector(self._counts[index]),
                    }
                )
            chunk_files[name] = {"data_version": data_version, "chunks": rows}
        posting_files: dict[str, Any] = {}
        sharded_terms: dict[int, dict[str, list[list[Any]]]] = {}
        for term in sorted(postings):
            shard = fnv1a_32(term) % POSTING_SHARD_COUNT
            sharded_terms.setdefault(shard, {})[term] = postings[term]
        for shard in range(POSTING_SHARD_COUNT):
            name = f"postings-{shard:02d}.json"
            posting_files[name] = {"data_version": data_version, "terms": sharded_terms.get(shard, {})}
        manifest = {
            "version": 1,
            "kind": "bigram-tfidf-with-hashed-vector-foundation",
            "data_version": data_version,
            "generated_at_utc": generated_at_utc,
            "law_count": len(self._law_ids),
            "chunk_count": total,
            "chunk_shard_size": CHUNK_SHARD_SIZE,
            "posting_shards": POSTING_SHARD_COUNT,
            "vector_dim": VECTOR_DIM,
            "vector_encoding": "int8-base64",
            "dense_embedding_model": None,
            "files": {
                "chunks": sorted(chunk_files),
                "postings": sorted(posting_files),
            },
        }
        return {"manifest": manifest, "chunks": chunk_files, "postings": posting_files}

    def write(self, search_root: Path, *, data_version: str, generated_at_utc: str) -> dict[str, Any]:
        built = self.build(data_version=data_version, generated_at_utc=generated_at_utc)
        search_root.mkdir(parents=True, exist_ok=True)
        for group in ("chunks", "postings"):
            for name, data in built[group].items():
                (search_root / name).write_text(
                    json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
        manifest = built["manifest"]
        (search_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest


def build_search_index(laws: Iterable[dict[str, Any]]) -> SearchIndexBuilder:
    builder = SearchIndexBuilder()
    builder.add_laws(laws)
    return builder


def index_fingerprint(manifest: dict[str, Any]) -> str:
    source = f"{manifest.get('data_version')}:{manifest.get('chunk_count')}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
