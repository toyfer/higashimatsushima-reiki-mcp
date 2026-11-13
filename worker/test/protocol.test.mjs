import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";
import { mockFetch, pagesJson, request } from "./helpers.mjs";

test("notifications return 202 with empty body and do not execute tools", async () => {
  let called = false;
  const restore = mockFetch(async () => {
    called = true;
    return new Response("{}", { status: 200 });
  });
  try {
    const notifications = [
      { jsonrpc: "2.0", method: "ping" },
      { jsonrpc: "2.0", method: "initialize" },
      { jsonrpc: "2.0", method: "tools/list" },
      { jsonrpc: "2.0", method: "notifications/initialized" },
      { jsonrpc: "2.0", method: "tools/call", params: { name: "reiki_status", arguments: {} } },
    ];
    for (const message of notifications) {
      const res = await worker.fetch(request("/mcp", message), {});
      assert.equal(res.status, 202, JSON.stringify(message));
      assert.equal(await res.text(), "");
    }
    assert.equal(called, false);
  } finally {
    restore();
  }
});

test("mixed batch returns only non-notification responses and rejects empty batch", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const mixed = await worker.fetch(
      request("/mcp", [
        { jsonrpc: "1.0", method: "ping" },
        { jsonrpc: "2.0", method: "ping" },
        { jsonrpc: "2.0", id: 11, method: "ping" },
      ]),
      {}
    );
    assert.equal(mixed.status, 200);
    const body = await mixed.json();
    assert.equal(body.length, 2);
    assert.equal(body[0].error.code, -32600);
    assert.deepEqual(body[1], { jsonrpc: "2.0", id: 11, result: {} });

    const empty = await worker.fetch(request("/mcp", []), {});
    const emptyBody = await empty.json();
    assert.equal(emptyBody.error.code, -32600);
    assert.equal(emptyBody.id, null);
  } finally {
    restore();
  }
});

test("invalid JSON-RPC envelopes and bad id types return -32600 with id null and no execution", async () => {
  let called = false;
  const restore = mockFetch(async () => {
    called = true;
    return new Response("{}", { status: 200 });
  });
  try {
    const validIdInvalid = await worker.fetch(request("/mcp", { id: 5, method: "ping" }), {});
    const validIdBody = await validIdInvalid.json();
    assert.equal(validIdBody.error.code, -32600);
    assert.equal(validIdBody.id, 5);

    const badEnvelopes = [
      { jsonrpc: "1.0", method: "ping" },
      {},
      { jsonrpc: "2.0", id: true, method: "tools/call", params: { name: "reiki_status", arguments: {} } },
      { jsonrpc: "2.0", id: [], method: "tools/call", params: { name: "reiki_status", arguments: {} } },
      { jsonrpc: "2.0", id: {}, method: "tools/call", params: { name: "reiki_status", arguments: {} } },
    ];
    for (const badId of [true, [], {}]) {
      for (const malformed of [
        { jsonrpc: "1.0", method: "ping" },
        { jsonrpc: "2.0", method: 42 },
        { jsonrpc: "2.0", method: "" },
        { method: "ping" },
      ]) {
        badEnvelopes.push({ ...malformed, id: badId });
      }
    }
    for (const envelope of badEnvelopes) {
      const res = await worker.fetch(request("/mcp", envelope), {});
      const body = await res.json();
      assert.equal(body.error.code, -32600, JSON.stringify(envelope));
      assert.equal(body.id, null, JSON.stringify(envelope));
    }
    assert.equal(called, false);
  } finally {
    restore();
  }
});

test("valid ids echo on ping and malformed envelope with valid id echoes id", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    for (const goodId of ["req-1", 42, null]) {
      const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: goodId, method: "ping" }), {});
      assert.deepEqual(await res.json(), { jsonrpc: "2.0", id: goodId, result: {} });
    }
    const malformed = await worker.fetch(request("/mcp", { jsonrpc: "1.0", id: "keep-me", method: "ping" }), {});
    const body = await malformed.json();
    assert.equal(body.error.code, -32600);
    assert.equal(body.id, "keep-me");
  } finally {
    restore();
  }
});

test("parse error returns -32700 with HTTP 400", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", "{not json"), {});
    assert.equal(res.status, 400);
    assert.equal((await res.json()).error.code, -32700);
  } finally {
    restore();
  }
});

test("initialize returns protocol version and server info", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const res = await worker.fetch(request("/mcp", { jsonrpc: "2.0", id: "init-1", method: "initialize", params: {} }), {});
    const body = await res.json();
    assert.equal(body.id, "init-1");
    assert.equal(body.result.protocolVersion, "2024-11-05");
    assert.equal(body.result.serverInfo.name, "higashimatsushima-reiki-mcp");
    assert.ok(body.result.capabilities.tools);
  } finally {
    restore();
  }
});

test("invalid tools/call params and unknown tools return -32602", async () => {
  const restore = mockFetch(pagesJson({}));
  try {
    const cases = [
      undefined,
      { name: 42, arguments: {} },
      { name: "reiki_status", arguments: [] },
      { name: "reiki_status", arguments: null },
      { name: "nope", arguments: {} },
      { name: "search_laws_by_title", arguments: {} },
      { name: "get_law", arguments: { law_id: "../bad" } },
    ];
    for (const [idx, params] of cases.entries()) {
      const msg = { jsonrpc: "2.0", id: idx + 1, method: "tools/call" };
      if (params !== undefined) msg.params = params;
      const body = await (await worker.fetch(request("/mcp", msg), {})).json();
      assert.equal(body.error.code, -32602, JSON.stringify(params));
    }
  } finally {
    restore();
  }
});

test("Pages failure in tools/call is a tool execution error", async () => {
  const restore = mockFetch(async () => new Response("down", { status: 503 }));
  try {
    const res = await worker.fetch(
      request("/mcp", { jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "reiki_status", arguments: {} } }),
      {}
    );
    const body = await res.json();
    assert.equal(body.error, undefined);
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /Pages fetch failed: 503/);
  } finally {
    restore();
  }
});

test("AUTH_TOKEN enforces Bearer auth on POST /mcp while keeping GET/live/health open", async () => {
  const restore = mockFetch(pagesJson({ ok: true, law_count: 7, expected_count: 7, failure_count: 0 }));
  try {
    const env = { AUTH_TOKEN: "test-secret" };
    const payload = { jsonrpc: "2.0", id: 1, method: "tools/list" };

    for (const headers of [{}, { Authorization: "Bearer wrong-token" }, { Authorization: "test-secret" }]) {
      const res = await worker.fetch(request("/mcp", payload, "POST", headers), env);
      assert.equal(res.status, 401, JSON.stringify(headers));
      assert.equal((await res.json()).error.code, -32001);
    }

    for (const scheme of ["Bearer", "bearer"]) {
      const res = await worker.fetch(request("/mcp", payload, "POST", { Authorization: `${scheme} test-secret` }), env);
      assert.equal(res.status, 200, scheme);
      const body = await res.json();
      assert.deepEqual(body.result.tools.map((t) => t.name), [
        "reiki_status",
        "search_laws_by_title",
        "search_laws_by_content",
        "get_law",
        "get_article",
        "get_toc",
        "get_unit",
      ]);
    }

    for (const path of ["/live", "/mcp", "/health"]) {
      const res = await worker.fetch(new Request(`http://localhost${path}`), env);
      assert.equal(res.status, 200, path);
    }
  } finally {
    restore();
  }
});

test("live returns 200 without touching Pages", async () => {
  let called = false;
  const restore = mockFetch(async () => {
    called = true;
    return new Response("down", { status: 503 });
  });
  try {
    const res = await worker.fetch(new Request("http://localhost/live"), {});
    assert.equal(res.status, 200);
    assert.equal((await res.json()).ok, true);
    assert.equal(called, false);
  } finally {
    restore();
  }
});

test("health returns 200 when healthy and 503 on failure states", async () => {
  const healthy = mockFetch(pagesJson({ ok: true, law_count: 1192, expected_count: 1192, failure_count: 0, data_version: "v1" }));
  try {
    const res = await worker.fetch(new Request("http://localhost/health"), {});
    assert.equal(res.status, 200);
    assert.equal((await res.json()).ok, true);
  } finally {
    healthy();
  }

  const unhealthyResponses = [
    async () => new Response("down", { status: 503 }),
    async () => new Response("not json", { status: 200, headers: { "Content-Type": "application/json" } }),
    pagesJson({ ok: false, law_count: 10, expected_count: 10, failure_count: 0 }),
    pagesJson({ ok: true, law_count: 5, selected_count: 5, failure_count: 0 }),
    pagesJson({ ok: true, law_count: 5, expected_count: 1192, selected_count: 5, failure_count: 0 }),
    pagesJson({ ok: true, law_count: 10, expected_count: 10, failure_count: 1 }),
  ];
  for (const [idx, responder] of unhealthyResponses.entries()) {
    const restore = mockFetch(responder);
    try {
      const res = await worker.fetch(new Request("http://localhost/health"), {});
      assert.equal(res.status, 503, `case ${idx}`);
      assert.equal((await res.json()).ok, false, `case ${idx}`);
    } finally {
      restore();
    }
  }
});
