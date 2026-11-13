import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

const PAGES_BASE = "https://pages.test";
const DATA_VERSION = "test-data-version";

const FORM_RESOURCE = {
  label: "様式第1号(第14条関係)",
  kind: "form",
  table_number: null,
  seq: 1,
  href: "honbun_1.rtf",
  image_url: "/reiki/honbun_1.png",
};

const TABLE_RESOURCE = {
  label: "別表第2(第5条関係)",
  kind: "appendix",
  table_number: 2,
  seq: 2,
  href: "honbun_2.rtf",
  image_url: "/reiki/honbun_2.png",
};

const baseLaw = (id, overrides) => ({
  id,
  title: `例規 ${id}`,
  source_url: `https://example.test/${id}`,
  data_version: DATA_VERSION,
  content_current_date: "令和8年6月26日",
  articles: [{ label: "第1条", heading: "(目的)", text: "この要綱は、災害対策本部の運営について定める。" }],
  supplements: [],
  ...overrides,
});

const MAPPED_LAW = baseLaw("r122RG00000002", {
  title: "東松島市災害対策本部運営要綱",
  appendix_tables: ["別表第1(第3条関係) 被害認定基準\n1 全壊 50パーセント以上", "別表第2(第5条関係)"],
  resources: [FORM_RESOURCE, TABLE_RESOURCE],
  appendix_table_resource_index: [null, 1],
});

const LEGACY_LAW = baseLaw("r122RG00000003", {
  appendix_tables: ["別表第1(第2条関係)"],
  resources: [{ ...TABLE_RESOURCE, label: "別表第1(第2条関係)", table_number: 1, seq: 1 }],
});

const BROKEN_MAPPING_LAW = baseLaw("r122RG00000004", {
  appendix_tables: ["別表第3(第9条関係)"],
  resources: [TABLE_RESOURCE],
  appendix_table_resource_index: [7],
});

const LAWS = new Map([MAPPED_LAW, LEGACY_LAW, BROKEN_MAPPING_LAW].map((law) => [law.id, law]));

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

function installPages() {
  const original = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const { pathname } = new URL(typeof input === "string" ? input : input.url);
    const lawMatch = pathname.match(/^\/api\/laws\/(.+)\.json$/);
    if (lawMatch) {
      const law = LAWS.get(lawMatch[1]);
      return law ? json(law) : json({ error: "not found" }, 404);
    }
    return json({ error: "not found" }, 404);
  };
  return () => {
    globalThis.fetch = original;
  };
}

async function callTool(name, args) {
  const response = await worker.fetch(
    new Request("https://worker.test/mcp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }),
    }),
    { PAGES_BASE }
  );
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.ok(payload.result, `tools/call returned no result: ${JSON.stringify(payload)}`);
  assert.ok(!payload.result.isError, payload.result.content?.[0]?.text);
  return JSON.parse(payload.result.content[0].text);
}

test("appendix table resource uses the explicit mapping, not the position", async () => {
  const restore = installPages();
  try {
    const unit = await callTool("get_unit", { law_id: MAPPED_LAW.id, kind: "appendix_table", n: 2 });
    assert.equal(unit.found, true);
    assert.equal(unit.resource?.label, "別表第2(第5条関係)");
    assert.equal(unit.resource?.href, "honbun_2.rtf");
    assert.equal(unit.content_status, "external_resource_only");
  } finally {
    restore();
  }
});

test("an inline appendix table never borrows the form resource that precedes it", async () => {
  const restore = installPages();
  try {
    const unit = await callTool("get_unit", { law_id: MAPPED_LAW.id, kind: "appendix_table", n: 1 });
    assert.equal(unit.found, true);
    assert.equal(unit.resource, null);
    assert.equal(unit.content_status, "complete");
    assert.ok(unit.text.includes("全壊"));
  } finally {
    restore();
  }
});

test("law scoped content search carries the appendix resource and status", async () => {
  const restore = installPages();
  try {
    const payload = await callTool("search_laws_by_content", { law_id: MAPPED_LAW.id, query: "別表第2" });
    const hit = payload.results.find((row) => String(row.label).startsWith("別表第2"));
    assert.ok(hit, JSON.stringify(payload.results));
    assert.equal(hit.resource?.href, "honbun_2.rtf");
    assert.equal(hit.content_status, "external_resource_only");
  } finally {
    restore();
  }
});

test("law scoped search keeps the resource when scope=law", async () => {
  const restore = installPages();
  try {
    const payload = await callTool("search_laws_by_content", {
      law_id: MAPPED_LAW.id,
      query: "別表第2",
      scope: "law",
    });
    const row = payload.results[0];
    assert.ok(row, JSON.stringify(payload.results));
    // The top level copies the first evidence entry, so both must carry the
    // resource an external-only table was published with (issue #76).
    assert.equal(row.content_status, "external_resource_only");
    assert.equal(row.resource?.href, "honbun_2.rtf");
    assert.equal(row.matches[0].resource?.href, "honbun_2.rtf");
    assert.equal(row.matches[0].content_status, "external_resource_only");
  } finally {
    restore();
  }
});

test("laws published before the mapping existed keep the positional fallback", async () => {
  const restore = installPages();
  try {
    const unit = await callTool("get_unit", { law_id: LEGACY_LAW.id, kind: "appendix_table", n: 1 });
    assert.equal(unit.resource?.label, "別表第1(第2条関係)");
    assert.equal(unit.content_status, "external_resource_only");
  } finally {
    restore();
  }
});

test("an out of range mapping entry resolves to no resource", async () => {
  const restore = installPages();
  try {
    const unit = await callTool("get_unit", { law_id: BROKEN_MAPPING_LAW.id, kind: "appendix_table", n: 1 });
    assert.equal(unit.resource, null);
    assert.equal(unit.content_status, "complete");
  } finally {
    restore();
  }
});
