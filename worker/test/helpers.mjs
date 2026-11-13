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
