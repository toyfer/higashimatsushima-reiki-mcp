import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import worker from "../src/index.js";

if (!globalThis.crypto) globalThis.crypto = webcrypto;

function request(path, body, method = "POST") {
  const init = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) init.body = typeof body === "string" ? body : JSON.stringify(body);
  return new Request(`http://localhost${path}`, init);
}

function mockFetch(impl) {
  const original = globalThis.fetch;
  globalThis.fetch = impl;
  return () => { globalThis.fetch = original; };
}

function pagesJson(data, status = 200) {
  return async () => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

test("notification ping returns no response body", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", method: "ping" }), {});
    assert.equal(res.status, 202);
    assert.equal(await res.text(), "");
  } finally { restore(); }
});

for (const method of ["initialize", "tools/list"]) {
  test(`notification ${method} returns no response body`, async () => {
    const restore = mockFetch(pagesJson({}));
    try {
      const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", method }), {});
      assert.equal(res.status, 202);
      assert.equal(await res.text(), "");
    } finally { restore(); }
  });
}

test("notification tools/call does not execute or respond", async () => {
  let called = false;
  const restore = mockFetch(async () => { called = true; return new Response("{}", { status: 200 }); });
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", method: "tools/call", params: { name: "reiki_status", arguments: {} } }), {});
    assert.equal(res.status, 202);
    assert.equal(called, false);
  } finally { restore(); }
});

test("notifications/initialized returns no response body", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", method: "notifications/initialized" }), {});
    assert.equal(res.status, 202);
  } finally { restore(); }
});

test("mixed batch returns only the request response", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", [{ jsonrpc: "2.0", method: "ping" }, { jsonrpc: "2.0", id: 9, method: "ping" }]), {});
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.deepEqual(body, [{ jsonrpc: "2.0", id: 9, result: {} }]);
  } finally { restore(); }
});

test("unknown tool is a JSON-RPC protocol error", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "nope", arguments: {} } }), {});
    const body = await res.json();
    assert.equal(body.error.code, -32602);
  } finally { restore(); }
});

test("missing required argument is a JSON-RPC protocol error", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "search_laws_by_title", arguments: {} } }), {});
    const body = await res.json();
    assert.equal(body.error.code, -32602);
  } finally { restore(); }
});

test("invalid law_id is a JSON-RPC protocol error", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "get_law", arguments: { law_id: "../bad" } } }), {});
    const body = await res.json();
    assert.equal(body.error.code, -32602);
  } finally { restore(); }
});

test("Pages failure in tools/call is a tool execution error", async () => {
  const restore = mockFetch(async () => new Response("down", { status: 503 }));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "reiki_status", arguments: {} } }), {});
    const body = await res.json();
    assert.equal(body.error, undefined);
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /Pages fetch failed: 503/);
  } finally { restore(); }
});

test("invalid JSON-RPC request returns -32600 not 500", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { id: 5, method: "ping" }), {});
    const body = await res.json();
    assert.equal(body.error.code, -32600);
  } finally { restore(); }
});

test("parse error still returns -32700", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", "{not json"), {});
    assert.equal(res.status, 400);
    const body = await res.json();
    assert.equal(body.error.code, -32700);
  } finally { restore(); }
});

test("health returns 200 when published API is healthy", async () => {
  const restore = mockFetch(pagesJson({ ok: true, law_count: 1192, expected_count: 1192, failure_count: 0, data_version: "v1" }));
  try {
    const res = await worker.fetch(new Request("http://localhost/health"), {});
    assert.equal(res.status, 200);
    assert.equal((await res.json()).ok, true);
  } finally { restore(); }
});

test("health returns 503 when Pages fetch fails", async () => {
  const restore = mockFetch(async () => new Response("down", { status: 503 }));
  try {
    const res = await worker.fetch(new Request("http://localhost/health"), {});
    assert.equal(res.status, 503);
    const body = await res.json();
    assert.equal(body.ok, false);
    assert.ok(body.published.error);
  } finally { restore(); }
});

test("health returns 503 when published ok is false", async () => {
  const restore = mockFetch(pagesJson({ ok: false, law_count: 10, expected_count: 10, failure_count: 0 }));
  try {
    const res = await worker.fetch(new Request("http://localhost/health"), {});
    assert.equal(res.status, 503);
    assert.equal((await res.json()).ok, false);
  } finally { restore(); }
});

test("health returns 503 on invalid published JSON", async () => {
  const restore = mockFetch(async () => new Response("not json", { status: 200, headers: { "Content-Type": "application/json" } }));
  try {
    const res = await worker.fetch(new Request("http://localhost/health"), {});
    assert.equal(res.status, 503);
  } finally { restore(); }
});

test("live returns 200 without touching Pages", async () => {
  let called = false;
  const restore = mockFetch(async () => { called = true; return new Response("down", { status: 503 }); });
  try {
    const res = await worker.fetch(new Request("http://localhost/live"), {});
    assert.equal(res.status, 200);
    assert.equal((await res.json()).ok, true);
    assert.equal(called, false);
  } finally { restore(); }
});

test("malformed id-less object is -32600, not a notification", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "1.0", method: "ping" }), {});
    const body = await res.json();
    assert.equal(body.error.code, -32600);
    assert.equal(body.id, null);
  } finally { restore(); }
});

test("empty object is -32600, not a notification", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", {}), {});
    assert.equal((await res.json()).error.code, -32600);
  } finally { restore(); }
});

test("mixed batch with malformed id-less object returns error plus request response", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", [{ jsonrpc: "1.0", method: "ping" }, { jsonrpc: "2.0", method: "ping" }, { jsonrpc: "2.0", id: 11, method: "ping" }]), {});
    const body = await res.json();
    assert.equal(body.length, 2);
    assert.equal(body[0].error.code, -32600);
    assert.deepEqual(body[1], { jsonrpc: "2.0", id: 11, result: {} });
  } finally { restore(); }
});

test("POST /mcp without token is 401 when AUTH_TOKEN is set", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/list" }), { AUTH_TOKEN: "test-secret" });
    assert.equal(res.status, 401);
    assert.equal((await res.json()).error.code, -32001);
  } finally { restore(); }
});

test("POST /mcp with wrong token is 401", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const init = { method: "POST", headers: { "Content-Type": "application/json", "Authorization": "Bearer wrong-token" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) };
    const res = await worker.fetch(new Request("http://localhost/mcp", init), { AUTH_TOKEN: "test-secret" });
    assert.equal(res.status, 401);
  } finally { restore(); }
});

test("POST /mcp with valid token returns tools/list", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const init = { method: "POST", headers: { "Content-Type": "application/json", "Authorization": "Bearer test-secret" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) };
    const res = await worker.fetch(new Request("http://localhost/mcp", init), { AUTH_TOKEN: "test-secret" });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.result.tools.length, 7);
    assert.deepEqual(body.result.tools.map((tool) => tool.name), [
      "reiki_status",
      "search_laws_by_title",
      "search_laws_by_content",
      "get_law",
      "get_article",
      "get_toc",
      "get_unit",
    ]);
  } finally { restore(); }
});

test("live and GET /mcp stay open when AUTH_TOKEN is set", async () => {
  const restore = mockFetch(pagesJson({ ok: true, law_count: 7, expected_count: 7, selected_count: 7, failure_count: 0 }));
  try {
    const live = await worker.fetch(new Request("http://localhost/live"), { AUTH_TOKEN: "test-secret" });
    assert.equal(live.status, 200);
    const desc = await worker.fetch(new Request("http://localhost/mcp"), { AUTH_TOKEN: "test-secret" });
    assert.equal(desc.status, 200);
    const health = await worker.fetch(new Request("http://localhost/health"), { AUTH_TOKEN: "test-secret" });
    assert.equal(health.status, 200);
  } finally { restore(); }
});

test("POST /mcp with raw token (no Bearer scheme) is 401", async () => {
  const restore = mockFetch(pagesJson({ ok: true, law_count: 7, expected_count: 7, failure_count: 0 }));
  try {
    const init = { method: "POST", headers: { "Content-Type": "application/json", "Authorization": "test-secret" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) };
    const res = await worker.fetch(new Request("http://localhost/mcp", init), { AUTH_TOKEN: "test-secret" });
    assert.equal(res.status, 401);
  } finally { restore(); }
});

test("POST /mcp with lowercase bearer scheme returns tools/list", async () => {
  const restore = mockFetch(pagesJson({ ok: true, law_count: 7, expected_count: 7, failure_count: 0 }));
  try {
    const init = { method: "POST", headers: { "Content-Type": "application/json", "Authorization": "bearer test-secret" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) };
    const res = await worker.fetch(new Request("http://localhost/mcp", init), { AUTH_TOKEN: "test-secret" });
    assert.equal(res.status, 200);
  } finally { restore(); }
});

test("health returns 503 when only selected_count matches but expected_count is missing (sample shape)", async () => {
  const restore = mockFetch(pagesJson({ ok: true, law_count: 5, selected_count: 5, failure_count: 0 }));
  try {
    const res = await worker.fetch(new Request("http://localhost/health"), {});
    assert.equal(res.status, 503);
  } finally { restore(); }
});

test("health returns 503 when expected_count differs from law count", async () => {
  const restore = mockFetch(pagesJson({ ok: true, law_count: 5, expected_count: 1192, selected_count: 5, failure_count: 0 }));
  try {
    const res = await worker.fetch(new Request("http://localhost/health"), {});
    assert.equal(res.status, 503);
  } finally { restore(); }
});

const DEFAULT_SEARCH_MANIFEST = {
  "/api/search/manifest.json": {
    version: 1,
    kind: "bigram-tfidf",
    data_version: "fx",
    chunk_shard_size: 500,
    posting_shards: 16,
  },
};

function pagesRouter(routes) {
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

function toolText(body) {
  return JSON.parse(body.result.content[0].text);
}

const TITLE_INDEX = {
  data_version: "fx",
  laws: [
    { id: "r122RG00000003", title: "東松島市手数料条例", ordinance_number: "条例第30号", classification: "第1編 総規", article_count: 4, source_url: "https://example.invalid/3.html", body_text: "x".repeat(5000) },
    { id: "r122RG00000001", title: "東松島市手数料条例", ordinance_number: "条例第10号", classification: "第1編 総規", article_count: 6, source_url: "https://example.invalid/1.html" },
    { id: "r122RG00000002", title: "東松島市税条例", ordinance_number: "条例第20号", classification: "第2編 税", article_count: 30, source_url: "https://example.invalid/2.html" },
  ],
};

const SAMPLE_LAW = {
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


for (const badId of [true, [], {}]) {
  test(`invalid JSON-RPC id type ${JSON.stringify(badId)} is -32600 with id null and no tool execution`, async () => {
    let called = false;
    const restore = mockFetch(async () => { called = true; return new Response("{}", { status: 200 }); });
    try {
      const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: badId, method: "tools/call", params: { name: "reiki_status", arguments: {} } }), {});
      const body = await res.json();
      assert.equal(body.error.code, -32600);
      assert.equal(body.id, null);
      assert.equal(called, false);
    } finally { restore(); }
  });
}

for (const badId of [true, [], {}]) {
  for (const malformed of [
    { jsonrpc: "1.0", method: "ping" },
    { jsonrpc: "2.0", method: 42 },
    { jsonrpc: "2.0", method: "" },
    { method: "ping" },
  ]) {
    test(`invalid id ${JSON.stringify(badId)} with malformed envelope ${JSON.stringify(malformed)} is -32600 with id null`, async () => {
      let called = false;
      const restore = mockFetch(async () => { called = true; return new Response("{}", { status: 200 }); });
      try {
        const res = await worker.fetch(request("/mcp", { ...malformed, id: badId }), {});
        const body = await res.json();
        assert.equal(body.error.code, -32600);
        assert.equal(body.id, null);
        assert.equal(called, false);
      } finally { restore(); }
    });
  }
}

test("malformed envelope with valid id echoes that id with -32600", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "1.0", id: "keep-me", method: "ping" }), {});
    const body = await res.json();
    assert.equal(body.error.code, -32600);
    assert.equal(body.id, "keep-me");
  } finally { restore(); }
});

for (const goodId of ["req-1", 42, null]) {
  test(`valid JSON-RPC id ${JSON.stringify(goodId)} is echoed by ping`, async () => {
    const restore = mockFetch(pagesJson({}));
    try {
      const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: goodId, method: "ping" }), {});
      const body = await res.json();
      assert.deepEqual(body, { jsonrpc: "2.0", id: goodId, result: {} });
    } finally { restore(); }
  });
}

test("initialize returns protocol version and server info", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: "init-1", method: "initialize", params: {} }), {});
    const body = await res.json();
    assert.equal(body.id, "init-1");
    assert.equal(body.result.protocolVersion, "2024-11-05");
    assert.equal(body.result.serverInfo.name, "higashimatsushima-reiki-mcp");
    assert.ok(body.result.capabilities.tools);
  } finally { restore(); }
});

test("empty batch is -32600", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", []), {});
    const body = await res.json();
    assert.equal(body.error.code, -32600);
    assert.equal(body.id, null);
  } finally { restore(); }
});

for (const [label, params] of [
  ["missing params", undefined],
  ["non-string name", { name: 42, arguments: {} }],
  ["array arguments", { name: "reiki_status", arguments: [] }],
  ["null arguments", { name: "reiki_status", arguments: null }],
]) {
  test(`tools/call with ${label} is -32602`, async () => {
    const restore = mockFetch(pagesJson({}));
    try {
      const message = { jsonrpc: "2.0", id: 7, method: "tools/call" };
      if (params !== undefined) message.params = params;
      const res = await worker.fetch(request("/mcp", message), {});
      const body = await res.json();
      assert.equal(body.error.code, -32602);
    } finally { restore(); }
  });
}

test("search_laws_by_title ranks exact title and breaks ties by id", async () => {
  const { impl } = pagesRouter({ "/api/search/title-index.json": TITLE_INDEX });
  const restore = mockFetch(impl);
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "search_laws_by_title", arguments: { query: "東松島市手数料条例" } } }), {});
    const payload = toolText(await res.json());
    assert.deepEqual(payload.laws.map((law) => law.id), ["r122RG00000001", "r122RG00000003"]);
    assert.equal(payload.count, 2);
  } finally { restore(); }
});

test("search_laws_by_title honors limit and returns zero hits", async () => {
  const { impl } = pagesRouter({ "/api/search/title-index.json": TITLE_INDEX });
  const restore = mockFetch(impl);
  try {
    const limited = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "search_laws_by_title", arguments: { query: "条例", limit: 2 } } }), {});
    assert.equal(toolText(await limited.json()).laws.length, 2);
    const empty = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "search_laws_by_title", arguments: { query: "存在しない条例名" } } }), {});
    const payload = toolText(await empty.json());
    assert.equal(payload.count, 0);
    assert.deepEqual(payload.laws, []);
  } finally { restore(); }
});

test("get_law fetches /api/laws/<law_id>.json and returns the law", async () => {
  const { impl, requested } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "get_law", arguments: { law_id: "r122RG00000002" } } }), {});
    const payload = toolText(await res.json());
    assert.equal(payload.id, "r122RG00000002");
    assert.equal(payload.title, SAMPLE_LAW.title);
    assert.ok(requested.some((url) => url.endsWith("/api/laws/r122RG00000002.json")), requested.join(","));
  } finally { restore(); }
});

test("get_article returns the matching article", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "get_article", arguments: { law_id: "r122RG00000002", article_label: "第2条" } } }), {});
    const payload = toolText(await res.json());
    assert.equal(payload.title, SAMPLE_LAW.title);
    assert.deepEqual(payload.articles.map((article) => article.label), ["第2条"]);
  } finally { restore(); }
});

test("get_article reports found:false with available labels", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "get_article", arguments: { law_id: "r122RG00000002", article_label: "第99条" } } }), {});
    const payload = toolText(await res.json());
    assert.equal(payload.found, false);
    assert.equal(payload.article_label, "第99条");
    assert.equal(payload.available_labels, "第1条, 第2条");
  } finally { restore(); }
});

test("health returns 503 when failure_count alone is nonzero", async () => {
  const restore = mockFetch(pagesJson({ ok: true, law_count: 10, expected_count: 10, failure_count: 1 }));
  try {
    const res = await worker.fetch(new Request("http://localhost/health"), {});
    assert.equal(res.status, 503);
    assert.equal((await res.json()).ok, false);
  } finally { restore(); }
});

const CONTENT_POSTINGS = {
  "/api/search/postings-03.json": { data_version: "fx", terms: { "随意": [[0, 1.5514]] } },
  "/api/search/postings-08.json": { data_version: "fx", terms: { "契約": [[0, 1.9229]] } },
  "/api/search/postings-13.json": { data_version: "fx", terms: { "意契": [[0, 1.5514]] } },
};
const CONTENT_CHUNKS = {
  "/api/search/chunks-000.json": { data_version: "fx", chunks: [
    { i: 0, law_id: "r122RG00000001", title: "契約規則", label: "第1条", heading: "(随意契約)", kind: "article", source_url: "https://example.invalid/1.html", snippet: "第1条 随意契約は600万円以下の場合にできる。" },
    { i: 1, law_id: "r122RG00000002", title: "手数料条例", label: "前文", heading: "", kind: "preamble", source_url: "https://example.invalid/1.html", snippet: "手数料の額は別表のとおりとする。" },
  ] },
};

test("search_laws_by_content returns chunk hits with source_url and bounded fetches", async () => {
  const { impl, requested } = pagesRouter({ ...CONTENT_POSTINGS, ...CONTENT_CHUNKS });
  const restore = mockFetch(impl);
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "search_laws_by_content", arguments: { query: "随意契約" } } }), {});
    const payload = toolText(await res.json());
    assert.equal(payload.count, 1);
    assert.equal(payload.results[0].law_id, "r122RG00000001");
    assert.equal(payload.results[0].label, "第1条");
    assert.equal(payload.results[0].source_url, "https://example.invalid/1.html");
    assert.ok(payload.pages_fetches <= 40, `pages_fetches=${payload.pages_fetches}`);
    assert.ok(payload.pages_fetches < 50, `pages_fetches=${payload.pages_fetches}`);
    assert.ok(requested.every((u) => u.includes("/api/search/")), requested.join(","));
    assert.ok(!requested.some((u) => u.endsWith("/api/laws/index.json")), requested.join(","));
  } finally { restore(); }
});

test("search_laws_by_content returns zero hits without chunk fetches when no posting matches", async () => {
  const emptyShards = {};
  for (let shard = 0; shard < 16; shard += 1) {
    emptyShards[`/api/search/postings-${String(shard).padStart(2, "0")}.json`] = { data_version: "fx", terms: {} };
  }
  const { impl, requested } = pagesRouter({ ...emptyShards, ...CONTENT_POSTINGS, ...CONTENT_CHUNKS });
  const restore = mockFetch(impl);
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "search_laws_by_content", arguments: { query: "宇宙開発" } } }), {});
    const payload = toolText(await res.json());
    assert.equal(payload.count, 0);
    assert.deepEqual(payload.results, []);
    assert.ok(!requested.some((u) => u.includes("chunks-")), requested.join(","));
  } finally { restore(); }
});

test("search_laws_by_content caps results per law", async () => {
  const many = { data_version: "fx", chunks: Array.from({length: 6}, (_, k) => ({ i: k, law_id: "r122RG00000009", title: "同一条例", label: `第${k+1}条`, heading: "", kind: "article", source_url: "https://example.invalid/9.html", snippet: `監査に関する第${k+1}条。` })) };
  const postings = {};
  // 監査 bigrams: 監査,査に,につ -> place all on their python shards via worker fnv is internal;
  // instead give every shard the same term entries so the test does not depend on shard numbers.
  for (let shard = 0; shard < 16; shard += 1) {
    postings[`/api/search/postings-${String(shard).padStart(2, "0")}.json`] = { data_version: "fx", terms: { "監査": [[0,3],[1,3],[2,3],[3,3],[4,3],[5,3]], "査に": [[0,1],[1,1],[2,1],[3,1],[4,1],[5,1]] } };
  }
  const { impl } = pagesRouter({ ...postings, "/api/search/chunks-000.json": many });
  const restore = mockFetch(impl);
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "search_laws_by_content", arguments: { query: "監査", limit: 10 } } }), {});
    const payload = toolText(await res.json());
    assert.equal(payload.count, 3);
  } finally { restore(); }
});

test("search_laws_by_content surfaces Pages failure as a tool error", async () => {
  const restore = mockFetch(async () => new Response("down", { status: 503 }));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "search_laws_by_content", arguments: { query: "監査" } } }), {});
    const body = await res.json();
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /Pages fetch failed: 503/);
  } finally { restore(); }
});

test("search_laws_by_content lazily fetches only chunk shards holding emitted candidates", async () => {
  // Index 0 -> chunks-000, index 500 -> chunks-001 (CHUNK_SHARD_SIZE=500).
  const postings = {};
  for (let shard = 0; shard < 16; shard += 1) {
    postings[`/api/search/postings-${String(shard).padStart(2, "0")}.json`] = { data_version: "fx", terms: { "監査": [[0, 3], [500, 2]] } };
  }
  const routes = {
    ...postings,
    "/api/search/chunks-000.json": { data_version: "fx", chunks: [{ i: 0, law_id: "r122RG00000021", title: "甲条例", label: "第1条", heading: "", kind: "article", source_url: "https://example.invalid/a.html", snippet: "監査の甲。" }] },
    "/api/search/chunks-001.json": { data_version: "fx", chunks: [{ i: 500, law_id: "r122RG00000022", title: "乙条例", label: "第2条", heading: "", kind: "article", source_url: "https://example.invalid/b.html", snippet: "監査の乙。" }] },
    "/api/search/chunks-002.json": { data_version: "fx", chunks: [{ i: 1000, law_id: "r122RG00000023", title: "丙条例", label: "第3条", heading: "", kind: "article", source_url: "https://example.invalid/c.html", snippet: "監査の丙。" }] },
  };
  const { impl, requested } = pagesRouter(routes);
  const restore = mockFetch(impl);
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: 5, method: "tools/call", params: { name: "search_laws_by_content", arguments: { query: "監査", limit: 2 } } }), {});
    const payload = toolText(await res.json());
    assert.equal(payload.count, 2);
    assert.deepEqual(payload.results.map((r) => r.law_id), ["r122RG00000021", "r122RG00000022"]);
    assert.ok(requested.some((u) => u.endsWith("chunks-000.json")), requested.join(","));
    assert.ok(requested.some((u) => u.endsWith("chunks-001.json")), requested.join(","));
    assert.ok(!requested.some((u) => u.endsWith("chunks-002.json")), requested.join(","));
  } finally { restore(); }
});

async function callTool(name, args, env = {}) {
  const res = await worker.fetch(
    request("/mcp", { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }),
    env
  );
  return res.json();
}

const SCOPE_LAW = {
  id: "r122RG00000070",
  title: "東松島市手数料徴収条例",
  data_version: "fx",
  content_current_date: "令和8年6月26日",
  source_url: "https://example.invalid/70.html",
  articles: [
    { label: "第1条", heading: "（趣旨）", text: "手数料は別表のとおりとする。" },
    { label: "第2条", heading: "（手数料）", text: "納税証明の手数料は300円とする。" },
  ],
  appendix_tables: ["別表(第2条関係)\n事務 手数料の名称 金額 納税証明 300円"],
  supplements: ["附則\n公布の日から施行する。"],
};

test("search_laws_by_title returns summaries from the title index without body_text", async () => {
  const { impl } = pagesRouter({ "/api/search/title-index.json": TITLE_INDEX });
  const restore = mockFetch(impl);
  try {
    const body = await callTool("search_laws_by_title", { query: "東松島市手数料条例", limit: 5 });
    const payload = toolText(body);
    assert.equal(payload.count, 2);
    assert.equal(payload.data_version, "fx");
    const first = payload.laws[0];
    assert.equal(first.id, "r122RG00000001");
    assert.equal(first.article_count, 6);
    assert.equal(first.source_url, "https://example.invalid/1.html");
    assert.ok(!("body_text" in first));
    assert.ok(!JSON.stringify(payload).includes("xxxxxxxxxx"));
  } finally { restore(); }
});

test("search_laws_by_title reports a missing title index instead of empty results", async () => {
  const restore = mockFetch(async () => new Response("not found", { status: 404 }));
  try {
    const body = await callTool("search_laws_by_title", { query: "条例" });
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /title index/i);
  } finally { restore(); }
});

test("search_laws_by_content rejects a single-character query", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const body = await callTool("search_laws_by_content", { query: "税" });
    assert.equal(body.error.code, -32602);
    assert.match(body.error.message, /at least 2/);
  } finally { restore(); }
});

test("search_laws_by_content reports per-law truncation", async () => {
  const many = {
    data_version: "fx",
    chunks: Array.from({ length: 6 }, (_, k) => ({
      i: k,
      law_id: "r122RG00000009",
      title: "同一条例",
      label: `第${k + 1}条`,
      heading: "",
      kind: "article",
      source_url: "https://example.invalid/9.html",
      snippet: `監査に関する第${k + 1}条。`,
    })),
  };
  const postings = {};
  for (let shard = 0; shard < 16; shard += 1) {
    postings[`/api/search/postings-${String(shard).padStart(2, "0")}.json`] = {
      data_version: "fx",
      terms: { "監査": [[0, 3], [1, 3], [2, 3], [3, 3], [4, 3], [5, 3]] },
    };
  }
  const { impl } = pagesRouter({ ...postings, "/api/search/chunks-000.json": many });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "監査", limit: 10 }));
    assert.equal(payload.count, 3);
    assert.equal(payload.truncated, true);
    assert.ok(payload.truncation_reasons.includes("max_results_per_law"), payload.truncation_reasons.join(","));
  } finally { restore(); }
});

test("search_laws_by_content fails loudly when the search index is not published", async () => {
  const restore = mockFetch(async () => new Response("not found", { status: 404 }));
  try {
    const body = await callTool("search_laws_by_content", { query: "随意契約" });
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /manifest/);
    assert.match(body.result.content[0].text, /full_build=true/);
  } finally { restore(); }
});

test("search_laws_by_content rejects a mismatched data_version instead of returning wrong laws", async () => {
  const stale = {};
  for (let shard = 0; shard < 16; shard += 1) {
    stale[`/api/search/postings-${String(shard).padStart(2, "0")}.json`] = { data_version: "old", terms: { "随意": [[0, 2]] } };
  }
  const { impl } = pagesRouter({ ...stale, ...CONTENT_CHUNKS });
  const restore = mockFetch(impl);
  try {
    const body = await callTool("search_laws_by_content", { query: "随意契約" });
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /version mismatch/);
  } finally { restore(); }
});

test("search_laws_by_content with law_id searches only that ordinance", async () => {
  const { impl, requested } = pagesRouter({ "/api/laws/r122RG00000070.json": SCOPE_LAW });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "手数料", law_id: "r122RG00000070", limit: 5 }));
    assert.ok(payload.count > 0);
    assert.ok(payload.results.every((row) => row.law_id === "r122RG00000070"));
    assert.equal(payload.pages_fetches, 1);
    assert.equal(payload.data_version, "fx");
    assert.ok(payload.results.some((row) => row.kind === "appendix_table"));
    assert.ok(!requested.some((url) => url.includes("/api/search/")), requested.join(","));
  } finally { restore(); }
});

test("search_laws_by_content with an unknown law_id does not fall back to the whole corpus", async () => {
  const { impl } = pagesRouter({});
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "手数料", law_id: "r999RG99999999" }));
    assert.equal(payload.found, false);
    assert.equal(payload.count, 0);
    assert.deepEqual(payload.results, []);
  } finally { restore(); }
});

test("get_law accepts an upper-case law id", async () => {
  const { impl, requested } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("get_law", { law_id: "R122RG00000002" }));
    assert.equal(payload.id, "r122RG00000002");
    assert.ok(requested.some((url) => url.endsWith("/api/laws/r122RG00000002.json")), requested.join(","));
  } finally { restore(); }
});

test("get_law distinguishes a missing law from a Pages outage", async () => {
  const { impl } = pagesRouter({});
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("get_law", { law_id: "r122RG99999999" }));
    assert.equal(payload.found, false);
    assert.equal(payload.reason, "not_found");
  } finally { restore(); }
});

test("get_article selects one paragraph", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", paragraph: 2 }));
    assert.equal(payload.found, true);
    assert.equal(payload.paragraph.number, 2);
    assert.equal(payload.paragraph.text, "第二項の本文。");
    assert.deepEqual(payload.paragraph.items, []);
  } finally { restore(); }
});

test("get_article selects one item and requires paragraph", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", paragraph: 1, item: 2 }));
    assert.equal(payload.paragraph.items.length, 1);
    assert.deepEqual(payload.paragraph.items[0], { label: "(2)", text: "土曜日" });
    const error = await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", item: 2 });
    assert.equal(error.error.code, -32602);
  } finally { restore(); }
});

test("get_article reports available paragraphs for an unknown paragraph", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", paragraph: 9 }));
    assert.equal(payload.found, false);
    assert.deepEqual(payload.available_paragraphs, [1, 2]);
  } finally { restore(); }
});

test("get_toc lists articles and units with pagination", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("get_toc", { law_id: "r122RG00000002" }));
    assert.equal(payload.article_count, 2);
    assert.equal(payload.supplement_count, 2);
    assert.equal(payload.appendix_table_count, 2);
    assert.deepEqual(payload.articles.map((article) => article.label), ["第1条", "第2条"]);
    assert.deepEqual(payload.supplements, ["附則1", "附則2"]);
    assert.deepEqual(payload.chapters.map((chapter) => chapter.text), ["第1章 総則", "第2章 雑則"]);
    assert.equal(payload.articles[0].chapter, "第1章");
    assert.equal(payload.articles[0].chapter_title, "総則");
    assert.deepEqual(payload.deleted_headings, []);
    assert.equal(payload.resources.length, 2);
    assert.equal(payload.resources[1].href, "word/r122FG00000002.rtf");
    assert.equal(payload.next_offset, null);
    const paged = toolText(await callTool("get_toc", { law_id: "r122RG00000002", limit: 1 }));
    assert.equal(paged.next_offset, 1);
  } finally { restore(); }
});

test("get_toc surfaces deleted section headings", async () => {
  const law = { ...SAMPLE_LAW, deleted_headings: ["第5節 鉱産税 削除"] };
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": law });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("get_toc", { law_id: "r122RG00000002" }));
    assert.deepEqual(payload.deleted_headings, ["第5節 鉱産税 削除"]);
  } finally { restore(); }
});

test("get_unit returns one appendix table or supplement", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const table = toolText(await callTool("get_unit", { law_id: "r122RG00000002", kind: "appendix_table", n: 2 }));
    assert.equal(table.found, true);
    assert.equal(table.unit_id, "r122RG00000002#appendix_table-2");
    assert.match(table.text, /別表第2/);
    // Heading-only appendix with a downloadable resource is flagged, not
    // presented as a complete table (issue #51).
    assert.equal(table.content_status, "external_resource_only");
    assert.equal(table.resource.href, "word/r122FG00000002.rtf");
    const complete = toolText(await callTool("get_unit", { law_id: "r122RG00000002", kind: "appendix_table", n: 1 }));
    assert.equal(complete.content_status, "complete");
    const supplement = toolText(await callTool("get_unit", { law_id: "r122RG00000002", kind: "supplement", n: 2 }));
    assert.equal(supplement.label, "附則2");
    assert.match(supplement.text, /改正規定/);
    const missing = toolText(await callTool("get_unit", { law_id: "r122RG00000002", kind: "supplement", n: 9 }));
    assert.equal(missing.found, false);
    assert.deepEqual(missing.available_n, [1, 2]);
  } finally { restore(); }
});

test("asof is rejected instead of silently returning the current version", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const body = await callTool("get_law", { law_id: "r122RG00000002", asof: "2020-04-01" });
    assert.equal(body.error.code, -32602);
    assert.match(body.error.message, /asof is not supported/);
  } finally { restore(); }
});

test("reiki_status reports whether the search index is published", async () => {
  const { impl } = pagesRouter({
    "/api/meta.json": { data_version: "fx", law_count: 1 },
    "/api/health.json": { ok: true, law_count: 1, expected_count: 1, failure_count: 0 },
    "/api/search/manifest.json": { data_version: "fx", kind: "bigram-tfidf", law_count: 1, chunk_count: 2, files: { chunks: ["chunks-000.json"], postings: ["postings-00.json"] } },
  });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("reiki_status", {}));
    assert.equal(payload.search.published, true);
    assert.equal(payload.search.chunk_count, 2);
  } finally { restore(); }
});

const EXACT_GRAMS = {
  "随意": [1, 2, 3],
  "意契": [1, 2, 3],
  "契約": [1, 2, 3, 4],
  "60": [0, 1, 4],
  "00": [0, 1, 4],
  "0万": [0, 1, 4],
  "万円": [0, 1, 4],
};

const EXACT_POSTINGS = (() => {
  const shard = { data_version: "fx", terms: {} };
  for (const [gram, indexes] of Object.entries(EXACT_GRAMS)) {
    shard.terms[gram] = indexes.map((index) => [index, 1]);
  }
  const routes = {};
  for (let s = 0; s < 16; s += 1) routes[`/api/search/postings-${String(s).padStart(2, "0")}.json`] = shard;
  return routes;
})();

const EXACT_CHUNKS = {
  "/api/search/chunks-000.json": {
    data_version: "fx",
    chunks: [
      { i: 0, law_id: "r122RG00000031", title: "資格基準", label: "別表第1", heading: "", kind: "appendix_table", source_url: "https://e/31", snippet: "評価点600点", text: "評価点600点、契約額500万円を基準とする。" },
      { i: 1, law_id: "r122RG00000032", title: "委託規程", label: "第3条", heading: "(随意契約)", kind: "article", source_url: "https://e/32", snippet: "随意契約は600万円以下", text: "随意契約は600万円以下の額で締結できる。" },
      { i: 2, law_id: "r122RG00000033", title: "別条例", label: "第2条", heading: "", kind: "article", source_url: "https://e/33", snippet: "随意契約の相手方", text: "随意契約の相手方は公募する。" },
      { i: 3, law_id: "r122RG00000034", title: "両建条例", label: "第1条", heading: "", kind: "article", source_url: "https://e/34", snippet: "随意契約の方法", text: "随意契約の方法は規則で定める。" },
      { i: 4, law_id: "r122RG00000034", title: "両建条例", label: "第2条", heading: "", kind: "article", source_url: "https://e/34", snippet: "600万円を超える", text: "600万円を超える契約は入札による。" },
    ],
  },
};

function exactRouter() {
  return pagesRouter({ ...EXACT_POSTINGS, ...EXACT_CHUNKS });
}

test("exact phrase matching rejects chunks that only share the bigrams", async () => {
  const { impl } = exactRouter();
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "600万円" }));
    const lawIds = payload.results.map((row) => row.law_id);
    assert.ok(!lawIds.includes("r122RG00000031"), lawIds.join(","));
    assert.deepEqual(lawIds.sort(), ["r122RG00000032", "r122RG00000034"]);
    assert.equal(payload.match_type, undefined);
    assert.ok(payload.results.every((row) => row.match_type === "exact"));
    assert.equal(payload.filtered_out_exact, 1);
    assert.equal(payload.completeness, "complete");
  } finally { restore(); }
});

test("exact:false keeps bigram-only candidates and labels them approximate", async () => {
  const { impl } = exactRouter();
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "600万円", exact: false }));
    assert.equal(payload.count, 3);
    // A contiguous hit stays exact; only the bigram-only chunk is approximate.
    const byLaw = Object.fromEntries(payload.results.map((row) => [row.law_id, row.match_type]));
    assert.deepEqual(byLaw, {
      r122RG00000031: "approximate",
      r122RG00000032: "exact",
      r122RG00000034: "exact",
    });
  } finally { restore(); }
});

test("snippets carry highlights that point at the matched term", async () => {
  const { impl } = pagesRouter({
    ...EXACT_POSTINGS,
    ...EXACT_CHUNKS,
    "/api/laws/r122RG00000032.json": {
      id: "r122RG00000032",
      title: "委託規程",
      data_version: "fx",
      source_url: "https://e/32",
      articles: [{ label: "第3条", heading: "(随意契約)", text: "随意契約は600万円以下の額で締結できる。" }],
    },
  });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "随意契約", law_id: "r122RG00000032" }));
    const hit = payload.results[0];
    assert.equal(hit.highlights.length > 0, true);
    const highlight = hit.highlights[0];
    assert.equal(highlight.term, "随意契約");
    assert.equal(highlight.match_type, "exact");
    assert.ok(hit.snippet.slice(highlight.start, highlight.end).includes("随意契約"), JSON.stringify(hit));
  } finally { restore(); }
});

test("chunk scope requires every term in the same chunk, law scope does not", async () => {
  const { impl } = exactRouter();
  const restore = mockFetch(impl);
  try {
    const chunkScope = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", scope: "chunk" }));
    assert.deepEqual(chunkScope.results.map((row) => row.law_id), ["r122RG00000032"]);
    assert.equal(chunkScope.operator, "AND");

    const lawScope = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", scope: "law" }));
    assert.deepEqual(lawScope.results.map((row) => row.law_id).sort(), ["r122RG00000032", "r122RG00000034"]);
    const twoProof = lawScope.results.find((row) => row.law_id === "r122RG00000034");
    assert.equal(twoProof.matches.length, 2);
    assert.deepEqual(twoProof.matched_terms.sort(), ["600万円", "随意契約"]);
    assert.equal(lawScope.group_by, "law");
  } finally { restore(); }
});

test("OR widens chunk scope to any single term", async () => {
  const { impl } = exactRouter();
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", operator: "OR", limit: 20 }));
    const lawIds = new Set(payload.results.map((row) => row.law_id));
    assert.ok(lawIds.has("r122RG00000033"), [...lawIds].join(","));
    assert.equal(payload.operator, "OR");
    assert.ok(payload.results.every((row) => row.unmatched_terms.length >= 0));
  } finally { restore(); }
});

test("search reports counters and index caps for completeness judgement", async () => {
  const { impl } = exactRouter();
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "随意契約" }));
    for (const key of ["candidates", "candidates_examined", "filtered_out_no_term", "filtered_out_exact", "skipped_per_law", "index_caps"]) {
      assert.ok(key in payload, key);
    }
    assert.equal(payload.index_caps.pages_fetch_limit, 46);
    assert.equal(payload.index_caps.posting_shard_limit, 10);
    assert.equal(payload.index_caps.candidate_scan_limit, 300);
    assert.ok("posting_terms" in payload.index_caps);
    assert.ok("posting_entries" in payload.index_caps);
  } finally { restore(); }
});
