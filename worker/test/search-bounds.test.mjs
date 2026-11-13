import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

const DATA_VERSION = "test-data-version";
const PAGES_BASE = "https://pages.test";

const CHUNKS = [
  {
    i: 0,
    law_id: "r122RG00000494",
    title: "災害資金利子補給金交付要綱",
    label: "第7条",
    heading: "(貸付条件)",
    kind: "article",
    source_url: "https://example.test/r122RG00000494",
    snippet: "ア 600万円",
    text: "貸付限度額は、次のいずれか低い額であること。 ア 600万円 イ 市が認定した被害額の合計額",
  },
  {
    i: 1,
    law_id: "r122RG00000486",
    title: "農業近代化資金利子補給補助金交付要綱",
    label: "第4条",
    heading: "(貸付条件)",
    kind: "article",
    source_url: "https://example.test/r122RG00000486",
    snippet: "法人 3,600万円",
    text: "貸付対象者ごとの貸付金の合計の限度額 個人 1,800万円 法人 3,600万円",
  },
  {
    i: 2,
    law_id: "r122RG00000002",
    title: "東松島市組織条例",
    label: "第1条",
    heading: "(目的)",
    kind: "article",
    source_url: "https://example.test/r122RG00000002",
    snippet: "この条例は、市の組織に関し必要な事項を定めるものとする。",
    text: "この条例は、市の組織に関し必要な事項を定めるものとする。",
  },
  {
    i: 3,
    law_id: "r122RG00000003",
    title: "東松島市議会会議規則",
    label: "附則",
    heading: "",
    kind: "supplement",
    source_url: "https://example.test/r122RG00000003",
    snippet: "この規則は、一部改正する。",
    text: "この規則は、一部改正する。",
  },
];

const LAW = {
  id: "r122RG00000494",
  title: "災害資金利子補給金交付要綱",
  source_url: "https://example.test/r122RG00000494",
  data_version: DATA_VERSION,
  content_current_date: "令和8年6月26日",
  articles: [
    {
      label: "第7条",
      heading: "(貸付条件)",
      text: "貸付条件は、次のとおりとする。 (1) 貸付限度額は、次のいずれか低い額であること。 ア 600万円",
      paragraphs: [
        {
          number: 1,
          text: "貸付条件は、次のとおりとする。",
          items: [{ label: "1", text: "ア 600万円" }],
        },
      ],
    },
  ],
  supplements: ["この要綱は、公布の日から施行する。"],
  appendix_tables: [],
  resources: [],
};

const normalize = (value) => String(value || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

const bigrams = (value) => {
  const compact = normalize(value);
  const out = [];
  for (let index = 0; index < compact.length - 1; index += 1) out.push(compact.slice(index, index + 2));
  return out;
};

const postings = new Map();
for (const chunk of CHUNKS) {
  for (const gram of new Set(bigrams(`${chunk.label} ${chunk.heading} ${chunk.text}`))) {
    if (!postings.has(gram)) postings.set(gram, []);
    postings.get(gram).push([chunk.i, 1.5]);
  }
}

const MANIFEST = {
  version: 1,
  kind: "bigram-tfidf",
  data_version: DATA_VERSION,
  generated_at_utc: "2026-11-13T00:00:00Z",
  law_count: 4,
  chunk_count: CHUNKS.length,
  chunk_shard_size: 500,
  posting_shards: 16,
  max_postings_per_term: 50,
  max_postings_per_law_per_term: 3,
  posting_terms: postings.size,
  posting_entries: 0,
  files: {
    chunks: ["chunks-000.json"],
    postings: Array.from({ length: 16 }, (_, shard) => `postings-${String(shard).padStart(2, "0")}.json`),
  },
};

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

function installPages() {
  const original = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const { pathname } = new URL(typeof input === "string" ? input : input.url);
    if (pathname === "/api/search/manifest.json") return json(MANIFEST);
    if (pathname === "/api/search/title-index.json") return json({ data_version: DATA_VERSION, laws: [] });
    if (pathname.startsWith("/api/search/postings-")) {
      return json({ data_version: DATA_VERSION, terms: Object.fromEntries(postings) });
    }
    if (pathname.startsWith("/api/search/chunks-")) return json({ data_version: DATA_VERSION, chunks: CHUNKS });
    if (pathname === `/api/laws/${LAW.id}.json`) return json(LAW);
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

test("exact search rejects a phrase that starts inside a longer number (#62)", async () => {
  const restore = installPages();
  try {
    const data = await callTool("search_laws_by_content", { query: "600万円", exact: true });
    assert.deepEqual(
      data.results.map((row) => row.law_id),
      ["r122RG00000494"]
    );
    assert.ok(data.filtered_out_exact >= 1);
    assert.equal(data.results[0].match_type, "exact");
    assert.match(data.results[0].snippet, /600万円/);
  } finally {
    restore();
  }
});

test("exact=false keeps contiguous phrases exact instead of dropping them (#63)", async () => {
  const restore = installPages();
  try {
    const data = await callTool("search_laws_by_content", { query: "600万円", exact: false });
    assert.equal(data.exact, false);
    const hit = data.results.find((row) => row.law_id === "r122RG00000494");
    assert.ok(hit, "the chunk holding the phrase must survive an approximate search");
    assert.equal(hit.match_type, "exact");
  } finally {
    restore();
  }
});

test("AND query without a common chunk returns counters instead of failing (#67)", async () => {
  const restore = installPages();
  try {
    const data = await callTool("search_laws_by_content", { query: "一部改正 第2章", operator: "AND", scope: "chunk" });
    assert.equal(data.count, 0);
    assert.equal(data.completeness, "complete");
    assert.ok(data.filtered_out_no_term + data.filtered_out_exact >= 1);
    assert.equal(data.index_caps.snippet_window_chars, 280);
  } finally {
    restore();
  }
});

test("get_article reports the published version for a whole article (#64)", async () => {
  const restore = installPages();
  try {
    const data = await callTool("get_article", { law_id: LAW.id, article_label: "第7条" });
    assert.equal(data.found, true);
    assert.equal(data.data_version, DATA_VERSION);
    assert.equal(data.content_current_date, "令和8年6月26日");
    assert.equal(data.articles.length, 1);
  } finally {
    restore();
  }
});

test("law_id scoped search reports the scope it applied and unit ids (#64)", async () => {
  const restore = installPages();
  try {
    const data = await callTool("search_laws_by_content", { query: "600万円", law_id: LAW.id, scope: "chunk" });
    assert.equal(data.scope, "chunk");
    assert.equal(data.group_by, "chunk");
    assert.equal(data.content_current_date, "令和8年6月26日");
    assert.equal(data.count, 1);
    assert.equal(data.results[0].unit_id, `${LAW.id}#article-第7条`);
    assert.equal(data.results[0].match_type, "exact");
  } finally {
    restore();
  }
});
