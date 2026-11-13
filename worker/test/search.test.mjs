import test from "node:test";
import assert from "node:assert/strict";
import { SAMPLE_LAW, callTool, mockFetch, pagesJson, pagesRouter, toolText } from "./helpers.mjs";

const CONTENT_POSTINGS = {
  "/api/search/postings-03.json": { data_version: "fx", terms: { 随意: [[0, 1.5514]] } },
  "/api/search/postings-08.json": { data_version: "fx", terms: { 契約: [[0, 1.9229]] } },
  "/api/search/postings-13.json": { data_version: "fx", terms: { 意契: [[0, 1.5514]] } },
};
const CONTENT_CHUNKS = {
  "/api/search/chunks-000.json": {
    data_version: "fx",
    chunks: [
      { i: 0, law_id: "r122RG00000001", title: "契約規則", label: "第1条", heading: "(随意契約)", kind: "article", source_url: "https://example.invalid/1.html", snippet: "第1条 随意契約は600万円以下の場合にできる。" },
      { i: 1, law_id: "r122RG00000002", title: "手数料条例", label: "前文", heading: "", kind: "preamble", source_url: "https://example.invalid/1.html", snippet: "手数料の額は別表のとおりとする。" },
    ],
  },
};

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

const EXACT_GRAMS = {
  随意: [1, 2, 3],
  意契: [1, 2, 3],
  契約: [1, 2, 3, 4],
  "60": [0, 1, 4],
  "00": [0, 1, 4],
  "0万": [0, 1, 4],
  万円: [0, 1, 4],
};

function makeAllShards(terms) {
  const shard = { data_version: "fx", terms };
  const routes = {};
  for (let s = 0; s < 16; s += 1) routes[`/api/search/postings-${String(s).padStart(2, "0")}.json`] = shard;
  return routes;
}

const EXACT_POSTINGS = makeAllShards(
  Object.fromEntries(Object.entries(EXACT_GRAMS).map(([gram, indexes]) => [gram, indexes.map((index) => [index, 1])]))
);

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

test("search_laws_by_content returns chunk hits with bounded fetches and skips chunk fetches on zero hits", async () => {
  const { impl, requested } = pagesRouter({ ...CONTENT_POSTINGS, ...CONTENT_CHUNKS });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "随意契約" }));
    assert.equal(payload.count, 1);
    assert.equal(payload.results[0].law_id, "r122RG00000001");
    assert.equal(payload.results[0].label, "第1条");
    assert.equal(payload.results[0].source_url, "https://example.invalid/1.html");
    assert.ok(payload.pages_fetches <= 40);
    assert.ok(requested.every((u) => u.includes("/api/search/")));
    assert.ok(!requested.some((u) => u.endsWith("/api/laws/index.json")));
  } finally {
    restore();
  }

  const zeroRouter = pagesRouter({ ...makeAllShards({}), ...CONTENT_CHUNKS });
  const restoreZero = mockFetch(zeroRouter.impl);
  try {
    const empty = toolText(await callTool("search_laws_by_content", { query: "宇宙開発" }));
    assert.equal(empty.count, 0);
    assert.deepEqual(empty.results, []);
    assert.ok(!zeroRouter.requested.some((u) => u.includes("chunks-")));
  } finally {
    restoreZero();
  }
});

test("search_laws_by_content caps results per law and reports truncation", async () => {
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
  const { impl } = pagesRouter({
    ...makeAllShards({ 監査: [[0, 3], [1, 3], [2, 3], [3, 3], [4, 3], [5, 3]] }),
    "/api/search/chunks-000.json": many,
  });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "監査", limit: 10 }));
    assert.equal(payload.count, 3);
    assert.equal(payload.truncated, true);
    assert.ok(payload.truncation_reasons.includes("max_results_per_law"));
  } finally {
    restore();
  }
});

test("search_laws_by_content lazily fetches only chunk shards holding emitted candidates", async () => {
  const routes = {
    ...makeAllShards({ 監査: [[0, 3], [500, 2]] }),
    "/api/search/chunks-000.json": { data_version: "fx", chunks: [{ i: 0, law_id: "r122RG00000021", title: "甲", label: "第1条", heading: "", kind: "article", source_url: "https://e/a", snippet: "監査の甲。" }] },
    "/api/search/chunks-001.json": { data_version: "fx", chunks: [{ i: 500, law_id: "r122RG00000022", title: "乙", label: "第2条", heading: "", kind: "article", source_url: "https://e/b", snippet: "監査の乙。" }] },
    "/api/search/chunks-002.json": { data_version: "fx", chunks: [{ i: 1000, law_id: "r122RG00000023", title: "丙", label: "第3条", heading: "", kind: "article", source_url: "https://e/c", snippet: "監査の丙。" }] },
  };
  const { impl, requested } = pagesRouter(routes);
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "監査", limit: 2 }));
    assert.deepEqual(payload.results.map((r) => r.law_id), ["r122RG00000021", "r122RG00000022"]);
    assert.ok(requested.some((u) => u.endsWith("chunks-000.json")));
    assert.ok(requested.some((u) => u.endsWith("chunks-001.json")));
    assert.ok(!requested.some((u) => u.endsWith("chunks-002.json")));
  } finally {
    restore();
  }
});

test("search_laws_by_content rejects single-char queries and fails loudly on missing/stale/down index", async () => {
  const rSingle = mockFetch(pagesJson({}));
  try {
    const body = await callTool("search_laws_by_content", { query: "税" });
    assert.equal(body.error.code, -32602);
    assert.match(body.error.message, /at least 2/);
  } finally {
    rSingle();
  }

  for (const [status, pattern] of [
    [503, /Pages fetch failed: 503/],
    [404, /manifest/],
  ]) {
    const restore = mockFetch(async () => new Response("err", { status }));
    try {
      const body = await callTool("search_laws_by_content", { query: "随意契約" });
      assert.equal(body.result.isError, true);
      assert.match(body.result.content[0].text, pattern);
    } finally {
      restore();
    }
  }

  const stale = {};
  for (let s = 0; s < 16; s += 1) stale[`/api/search/postings-${String(s).padStart(2, "0")}.json`] = { data_version: "old", terms: { 随意: [[0, 2]] } };
  const restoreStale = mockFetch(pagesRouter({ ...stale, ...CONTENT_CHUNKS }).impl);
  try {
    const body = await callTool("search_laws_by_content", { query: "随意契約" });
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /version mismatch/);
  } finally {
    restoreStale();
  }
});

test("search_laws_by_content with law_id searches only that ordinance and handles unknown law_id", async () => {
  const { impl, requested } = pagesRouter({ "/api/laws/r122RG00000070.json": SCOPE_LAW });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "手数料", law_id: "r122RG00000070", limit: 5 }));
    assert.ok(payload.count > 0);
    assert.ok(payload.results.every((row) => row.law_id === "r122RG00000070"));
    assert.equal(payload.pages_fetches, 1);
    assert.equal(payload.data_version, "fx");
    assert.ok(payload.results.some((row) => row.kind === "appendix_table"));
    assert.ok(!requested.some((url) => url.includes("/api/search/")));

    const unknown = toolText(await callTool("search_laws_by_content", { query: "手数料", law_id: "r999RG99999999" }));
    assert.equal(unknown.found, false);
    assert.equal(unknown.count, 0);
    assert.deepEqual(unknown.results, []);
  } finally {
    restore();
  }
});

test("law-scoped search does not repeat a heading-only appendix label", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "別表第2", law_id: "r122RG00000002" }));
    const row = payload.results.find((item) => item.kind === "appendix_table");
    assert.ok(row, JSON.stringify(payload.results));
    assert.ok(!row.snippet.startsWith("別表第2 別表第2"), row.snippet);
    assert.equal(row.snippet.match(/別表第2/g).length, 1, row.snippet);
  } finally {
    restore();
  }
});

test("exact vs approximate matching, scope=chunk/law, OR operator, highlights, and index_caps", async () => {
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
    const exact = toolText(await callTool("search_laws_by_content", { query: "600万円" }));
    assert.deepEqual(exact.results.map((r) => r.law_id).sort(), ["r122RG00000032", "r122RG00000034"]);
    assert.ok(exact.results.every((r) => r.match_type === "exact"));
    assert.equal(exact.filtered_out_exact, 1);
    assert.equal(exact.completeness, "complete");

    const approx = toolText(await callTool("search_laws_by_content", { query: "600万円", exact: false }));
    assert.deepEqual(Object.fromEntries(approx.results.map((r) => [r.law_id, r.match_type])), {
      r122RG00000031: "approximate",
      r122RG00000032: "exact",
      r122RG00000034: "exact",
    });

    const chunkScope = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", scope: "chunk" }));
    assert.deepEqual(chunkScope.results.map((r) => r.law_id), ["r122RG00000032"]);
    assert.equal(chunkScope.operator, "AND");

    const lawScope = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", scope: "law" }));
    assert.deepEqual(lawScope.results.map((r) => r.law_id).sort(), ["r122RG00000032", "r122RG00000034"]);
    const twoProof = lawScope.results.find((r) => r.law_id === "r122RG00000034");
    assert.equal(twoProof.matches.length, 2);
    assert.deepEqual(twoProof.matched_terms.sort(), ["600万円", "随意契約"]);
    assert.equal(lawScope.group_by, "law");

    const orScope = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", operator: "OR", limit: 20 }));
    assert.ok(orScope.results.some((r) => r.law_id === "r122RG00000033"));
    assert.equal(orScope.operator, "OR");

    const hlPayload = toolText(await callTool("search_laws_by_content", { query: "随意契約", law_id: "r122RG00000032" }));
    const [hl] = hlPayload.results[0].highlights;
    assert.equal(hl.term, "随意契約");
    assert.equal(hl.match_type, "exact");
    assert.ok(hlPayload.results[0].snippet.slice(hl.start, hl.end).includes("随意契約"));

    const capsPayload = toolText(await callTool("search_laws_by_content", { query: "随意契約" }));
    for (const key of ["candidates", "candidates_examined", "filtered_out_no_term", "filtered_out_exact", "skipped_per_law", "index_caps"]) {
      assert.ok(key in capsPayload, key);
    }
    assert.equal(capsPayload.index_caps.pages_fetch_limit, 46);
    assert.equal(capsPayload.index_caps.posting_shard_limit, 10);
    assert.equal(capsPayload.index_caps.candidate_scan_limit, 300);
    assert.ok("posting_terms" in capsPayload.index_caps);
    assert.ok("posting_entries" in capsPayload.index_caps);
  } finally {
    restore();
  }
});

test("scope=law keeps the resource of the appendix chunk it cites and heading-only snippet avoids duplication", async () => {
  const routes = {
    ...makeAllShards({
      別表: [[0, 1.6]],
      表第: [[0, 1.6]],
      第2: [[0, 1.6]],
      第4: [[2, 1.4]],
      随意: [[1, 1.4]],
      意契: [[1, 1.4]],
      契約: [[1, 1.4]],
    }),
    "/api/search/chunks-000.json": {
      data_version: "fx",
      chunks: [
        {
          i: 0,
          law_id: "r122RG00000042",
          title: "委託規程",
          label: "別表第2(第5条関係)",
          heading: "",
          kind: "appendix_table",
          content_status: "external_resource_only",
          resource: { label: "別表第2(第5条関係)", href: "honbun_2.rtf", image_url: "" },
          source_url: "https://e/42",
          snippet: "別表第2(第5条関係)",
          text: "別表第2(第5条関係)",
        },
        {
          i: 1,
          law_id: "r122RG00000042",
          title: "委託規程",
          label: "第3条",
          heading: "(随意契約)",
          kind: "article",
          source_url: "https://e/42",
          snippet: "随意契約は別表第2による。",
          text: "随意契約は別表第2による。",
        },
        {
          i: 2,
          law_id: "r122RG00000041",
          title: "文書規程",
          label: "別表第4(第21条関係)",
          heading: "",
          kind: "appendix_table",
          content_status: "external_resource_only",
          resource: { label: "別表第4(第21条関係)", href: "word/r122FG00002360.rtf", image_url: "" },
          source_url: "https://e/41",
          snippet: "別表第4(第21条関係)",
          text: "別表第4(第21条関係)",
        },
      ],
    },
  };
  const { impl } = pagesRouter(routes);
  const restore = mockFetch(impl);
  try {
    const scopeLaw = toolText(await callTool("search_laws_by_content", { query: "別表第2 随意契約", scope: "law" }));
    assert.equal(scopeLaw.count, 1);
    const row = scopeLaw.results[0];
    assert.equal(row.kind, "appendix_table");
    assert.equal(row.label, "別表第2(第5条関係)");
    assert.equal(row.content_status, "external_resource_only");
    assert.equal(row.resource?.href, "honbun_2.rtf");
    assert.equal(row.matches.length, 2);

    const headingOnly = toolText(await callTool("search_laws_by_content", { query: "別表第4" }));
    assert.equal(headingOnly.results[0].snippet, "別表第4(第21条関係)");
    assert.equal(headingOnly.results[0].resource.href, "word/r122FG00002360.rtf");
  } finally {
    restore();
  }
});
