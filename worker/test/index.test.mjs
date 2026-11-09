import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

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
  const restore = mockFetch(pagesJson({ ok: false, law_count: 10, failure_count: 2 }));
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
    assert.equal(body.result.tools.length, 4);
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
