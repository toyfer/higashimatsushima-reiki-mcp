import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import worker from "../src/index.js";

if (!globalThis.crypto) globalThis.crypto = webcrypto;

export const DEFAULT_SEARCH_MANIFEST = {
  "/api/search/manifest.json": {
    version: 1,
    kind: "bigram-tfidf",
    data_version: "fx",
    chunk_shard_size: 500,
    posting_shards: 16,
  },
};

export function request(path, body, method = "POST", headers = {}) {
  const init = { method, headers: { "Content-Type": "application/json", ...headers } };
  if (body !== undefined) init.body = typeof body === "string" ? body : JSON.stringify(body);
  return new Request(`http://localhost${path}`, init);
}

export function mockFetch(impl) {
  const original = globalThis.fetch;
  globalThis.fetch = impl;
  return () => {
    globalThis.fetch = original;
  };
}

export function pagesJson(data, status = 200) {
  return async () => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

export function pagesRouter(routes) {
  const requested = [];
  const merged = { ...DEFAULT_SEARCH_MANIFEST, ...routes };
  const impl = async (url) => {
    const text = String(url);
    requested.push(text);
    const pathname = new URL(text).pathname;
    for (const [suffix, data] of Object.entries(merged)) {
      if (pathname.endsWith(suffix)) {
        return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
      }
    }
    return new Response("not found", { status: 404 });
  };
  return { impl, requested };
}

export async function callTool(name, args, env = {}) {
  const res = await worker.fetch(
    request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }),
    env
  );
  return res.json();
}

export function toolText(body) {
  assert.ok(body?.result?.content?.[0]?.text, `unexpected response: ${JSON.stringify(body)}`);
  return JSON.parse(body.result.content[0].text);
}

function fnv1a32(value) {
  let result = 2166136261;
  for (const char of String(value)) {
    result ^= char.codePointAt(0);
    result = Math.imul(result, 16777619) >>> 0;
  }
  return result >>> 0;
}

function extractBigrams(value) {
  const compact = String(value || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  const out = [];
  for (let i = 0; i < compact.length - 1; i += 1) out.push(compact.slice(i, i + 2));
  return out;
}

export function buildSearchRoutes(chunks, extraRoutes = {}, options = {}) {
  const dataVersion = options.dataVersion ?? "fx";
  const chunkShardSize = options.chunkShardSize ?? 500;
  const postingShards = Array.from({ length: 16 }, () => ({}));
  const normalizedChunks = chunks.map((chunk, idx) => ({
    i: chunk.i ?? idx,
    source_url: chunk.source_url ?? `https://example.invalid/${chunk.law_id || idx}.html`,
    heading: chunk.heading ?? "",
    snippet: chunk.snippet ?? chunk.text ?? "",
    ...chunk,
  }));

  let postingEntries = 0;
  const termsSet = new Set();
  for (const chunk of normalizedChunks) {
    const raw = `${chunk.label || ""} ${chunk.heading || ""} ${chunk.text ?? chunk.snippet ?? ""}`;
    const weight = chunk.weight ?? 1.5;
    for (const gram of new Set(extractBigrams(raw))) {
      const shard = fnv1a32(gram) % 16;
      if (!postingShards[shard][gram]) postingShards[shard][gram] = [];
      postingShards[shard][gram].push([chunk.i, weight]);
      termsSet.add(gram);
      postingEntries += 1;
    }
  }

  const routes = {};
  const chunkFiles = [];
  for (let offset = 0, shardIdx = 0; offset < normalizedChunks.length || shardIdx === 0; offset += chunkShardSize, shardIdx += 1) {
    const filename = `chunks-${String(shardIdx).padStart(3, "0")}.json`;
    chunkFiles.push(filename);
    const slice = normalizedChunks.slice(offset, offset + chunkShardSize).map(({ weight: _w, ...rest }) => rest);
    routes[`/api/search/${filename}`] = { data_version: dataVersion, chunks: slice };
    if (offset + chunkShardSize >= normalizedChunks.length) break;
  }

  const postingFiles = postingShards.map((terms, shardIdx) => {
    const filename = `postings-${String(shardIdx).padStart(2, "0")}.json`;
    routes[`/api/search/${filename}`] = { data_version: dataVersion, terms };
    return filename;
  });

  routes["/api/search/manifest.json"] = {
    version: 1,
    kind: "bigram-tfidf",
    data_version: dataVersion,
    generated_at_utc: "2026-11-15T00:00:00Z",
    law_count: new Set(normalizedChunks.map((c) => c.law_id)).size,
    chunk_count: normalizedChunks.length,
    chunk_shard_size: chunkShardSize,
    posting_shards: 16,
    max_postings_per_term: options.maxPostingsPerTerm ?? 50,
    max_postings_per_law_per_term: options.maxPostingsPerLawPerTerm ?? 3,
    posting_terms: termsSet.size,
    posting_entries: postingEntries,
    files: { chunks: chunkFiles, postings: postingFiles },
  };

  return { ...routes, ...extraRoutes };
}

export const TITLE_INDEX = {
  data_version: "fx",
  laws: [
    { id: "r122RG00000003", title: "東松島市手数料条例", ordinance_number: "条例第30号", classification: "第1編 総規", article_count: 4, source_url: "https://example.invalid/3.html", body_text: "x".repeat(5000) },
    { id: "r122RG00000001", title: "東松島市手数料条例", ordinance_number: "条例第10号", classification: "第1編 総規", article_count: 6, source_url: "https://example.invalid/1.html" },
    { id: "r122RG00000002", title: "東松島市税条例", ordinance_number: "条例第20号", classification: "第2編 税", article_count: 30, source_url: "https://example.invalid/2.html" },
  ],
};

export const SAMPLE_LAW = {
  id: "r122RG00000002",
  title: "東松島市の休日を定める条例",
  data_version: "fx",
  content_current_date: "令和8年6月26日",
  source_url: "https://example.invalid/2.html",
  articles: [
    {
      label: "第1条",
      heading: "（市の休日）",
      chapter: "第1章",
      chapter_title: "総則",
      paragraphs: [
        { number: 1, text: "市の休日を定める。", items: [{ label: "(1)", text: "日曜日" }, { label: "(2)", text: "土曜日" }] },
        { number: 2, text: "第二項の本文。", items: [] },
      ],
    },
    { label: "第2条", heading: "（期限の特例）", paragraphs: [{ number: 1, text: "期限の特例を定める。", items: [] }] },
  ],
  appendix_tables: ["別表(第2条関係)\n事務 名称 金額", "別表第2(第2条関係)"],
  supplements: ["附則\nこの条例は、公布の日から施行する。", "附則(平成18年3月20日条例第13号)\n改正規定。"],
  chapters: [
    { kind: "chapter", number: "第1章", title: "総則", text: "第1章 総則" },
    { kind: "chapter", number: "第2章", title: "雑則", text: "第2章 雑則" },
  ],
  resources: [null, { label: "別表第2(第2条関係)", href: "word/r122FG00000002.rtf", image_url: "word/r122FG00000002s.png" }],
  history: [{ date: "平成17年4月1日", number: "条例第2号" }],
};
