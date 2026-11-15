import test from "node:test";
import assert from "node:assert/strict";
import { SAMPLE_LAW, buildSearchRoutes, callTool, mockFetch, pagesJson, pagesRouter, toolText } from "./helpers.mjs";

const CORPUS_CHUNKS = [
  {
    i: 0,
    law_id: "r122RG00000031",
    title: "資格基準",
    label: "別表第1",
    kind: "appendix_table",
    weight: 5,
    text: "評価点600点、契約額500万円を基準とする。",
  },
  {
    i: 1,
    law_id: "r122RG00000032",
    title: "委託規程",
    label: "第3条",
    heading: "(随意契約)",
    kind: "article",
    weight: 1,
    text: "随意契約は600万円以下の額で締結できる。",
  },
  {
    i: 2,
    law_id: "r122RG00000033",
    title: "別条例",
    label: "第2条",
    kind: "article",
    text: "随意契約の相手方は公募する。",
  },
  {
    i: 3,
    law_id: "r122RG00000034",
    title: "両建条例",
    label: "第1条",
    kind: "article",
    text: "随意契約の方法は規則で定める。",
  },
  {
    i: 4,
    law_id: "r122RG00000034",
    title: "両建条例",
    label: "第2条",
    kind: "article",
    text: "600万円を超える契約は入札による。",
  },
  {
    i: 5,
    law_id: "r122RG00000486",
    title: "農業近代化資金利子補給補助金交付要綱",
    label: "第4条",
    heading: "(貸付条件)",
    kind: "article",
    text: "貸付対象者ごとの貸付金の合計の限度額 個人 1,800万円 法人 3,600万円",
  },
  {
    i: 6,
    law_id: "r122RG00000042",
    title: "委託規程",
    label: "別表第2(第5条関係)",
    kind: "appendix_table",
    weight: 3,
    content_status: "external_resource_only",
    resource: { label: "別表第2(第5条関係)", href: "honbun_2.rtf", image_url: "" },
    text: "別表第2(第5条関係)",
  },
  {
    i: 7,
    law_id: "r122RG00000042",
    title: "委託規程",
    label: "第3条",
    heading: "(随意契約)",
    kind: "article",
    weight: 1,
    text: "随意契約の手続は市長が定める。",
  },
  {
    i: 8,
    law_id: "r122RG00000041",
    title: "文書規程",
    label: "別表第4(第21条関係)",
    kind: "appendix_table",
    content_status: "external_resource_only",
    resource: { label: "別表第4(第21条関係)", href: "word/r122FG00002360.rtf", image_url: "" },
    text: "別表第4(第21条関係)",
  },
];

const CORPUS_ROUTES = buildSearchRoutes(CORPUS_CHUNKS, {
  "/api/laws/r122RG00000032.json": {
    id: "r122RG00000032",
    title: "委託規程",
    data_version: "fx",
    content_current_date: "令和8年6月26日",
    source_url: "https://example.invalid/r122RG00000032.html",
    articles: [{ label: "第3条", heading: "(随意契約)", text: "随意契約は600万円以下の額で締結できる。" }],
    appendix_tables: [],
    supplements: [],
  },
});

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
  appendix_tables: ["別表第1(第3条関係)\n事務 手数料の名称 金額 納税証明 300円", "別表第2(第5条関係)"],
  supplements: ["附則\n公布の日から施行する。"],
  resources: [{ label: "様式第1号", kind: "form", href: "form1.rtf", image_url: "" }, { label: "別表第2(第2条関係)", kind: "appendix", href: "honbun_2.rtf", image_url: "" }],
  appendix_table_resource_index: [null, 1],
};

test("search_laws_by_content returns bounded chunk hits and skips chunk fetches on zero hits", async () => {
  const { impl, requested } = pagesRouter(CORPUS_ROUTES);
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "公募" }));
    assert.equal(payload.count, 1);
    assert.equal(payload.results[0].law_id, "r122RG00000033");
    assert.equal(payload.results[0].label, "第2条");
    assert.ok(payload.pages_fetches <= 40);
    assert.ok(requested.every((u) => u.includes("/api/search/")));
    assert.ok(!requested.some((u) => u.endsWith("/api/laws/index.json")));
  } finally {
    restore();
  }

  const zeroRouter = pagesRouter(buildSearchRoutes([]));
  const restoreZero = mockFetch(zeroRouter.impl);
  try {
    const empty = toolText(await callTool("search_laws_by_content", { query: "存在しない規定" }));
    assert.equal(empty.count, 0);
    assert.equal(empty.completeness, "complete");
    assert.ok(!zeroRouter.requested.some((u) => u.includes("chunks-")));
  } finally {
    restoreZero();
  }
});

test("search_laws_by_content caps results per law and lazily fetches only needed chunk shards", async () => {
  const manyChunks = Array.from({ length: 5 }, (_, idx) => ({
    i: idx,
    law_id: "r122RG00000010",
    title: "多条条例",
    label: `第${idx + 1}条`,
    kind: "article",
    text: `第${idx + 1}条 契約の審査を行う。`,
  }));
  const multiLawChunks = [
    { i: 0, law_id: "r122RG00000001", title: "第一", label: "第1条", kind: "article", weight: 5, text: "入札参加資格を定める。" },
    { i: 1, law_id: "r122RG00000002", title: "第二", label: "第1条", kind: "article", weight: 4, text: "入札参加資格の登録。" },
    { i: 2, law_id: "r122RG00000003", title: "第三", label: "第1条", kind: "article", weight: 3, text: "入札参加資格の審査。" },
    ...Array.from({ length: 498 }, (_, idx) => ({
      i: idx + 3,
      law_id: `r122RG9999${String(idx).padStart(4, "0")}`,
      title: "無関係",
      label: "第1条",
      kind: "article",
      text: "無関係な条文。",
    })),
    { i: 501, law_id: "r122RG00000004", title: "第四", label: "第1条", kind: "article", weight: 1, text: "入札参加資格の特例。" },
  ];

  const { impl: capImpl } = pagesRouter(buildSearchRoutes(manyChunks));
  const restoreCap = mockFetch(capImpl);
  try {
    const capped = toolText(await callTool("search_laws_by_content", { query: "契約", limit: 10 }));
    assert.equal(capped.count, 3);
    assert.equal(capped.skipped_per_law, 2);
    assert.equal(capped.truncated, true);
    assert.ok(capped.truncation_reasons.includes("max_results_per_law"));
    assert.equal(capped.completeness, "complete");
  } finally {
    restoreCap();
  }

  const { impl: lazyImpl, requested } = pagesRouter(buildSearchRoutes(multiLawChunks));
  const restoreLazy = mockFetch(lazyImpl);
  try {
    const res = toolText(await callTool("search_laws_by_content", { query: "入札参加資格", limit: 1 }));
    assert.equal(res.count, 1);
    assert.ok(requested.some((u) => u.endsWith("/chunks-000.json")));
    assert.ok(!requested.some((u) => u.endsWith("/chunks-001.json")));
  } finally {
    restoreLazy();
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

  const staleRoutes = buildSearchRoutes(CORPUS_CHUNKS);
  for (const key of Object.keys(staleRoutes)) {
    if (key.includes("postings-")) staleRoutes[key] = { ...staleRoutes[key], data_version: "old" };
  }
  const restoreStale = mockFetch(pagesRouter(staleRoutes).impl);
  try {
    const body = await callTool("search_laws_by_content", { query: "随意契約" });
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /version mismatch/);
  } finally {
    restoreStale();
  }
});

test("exact verification blocks number-boundary false hits, ranks exact above approximate, and exposes counters", async () => {
  const { impl } = pagesRouter(CORPUS_ROUTES);
  const restore = mockFetch(impl);
  try {
    const exact = toolText(await callTool("search_laws_by_content", { query: "600万円", exact: true }));
    assert.deepEqual(exact.results.map((r) => r.law_id).sort(), ["r122RG00000032", "r122RG00000034"]);
    assert.ok(!exact.results.some((r) => r.law_id === "r122RG00000486"));
    assert.ok(!exact.results.some((r) => r.law_id === "r122RG00000031"));
    assert.ok(exact.filtered_out_exact >= 2);
    assert.equal(exact.completeness, "complete");

    const approx = toolText(await callTool("search_laws_by_content", { query: "600万円", exact: false, limit: 5 }));
    assert.equal(approx.exact, false);
    assert.equal(approx.results[0].match_type, "exact");
    const types = approx.results.map((row) => row.match_type);
    const lastExact = types.lastIndexOf("exact");
    const firstApprox = types.indexOf("approximate");
    assert.ok(firstApprox === -1 || firstApprox > lastExact, `exact must precede approximate: ${types}`);
    assert.equal(approx.results.find((r) => r.law_id === "r122RG00000031")?.match_type, "approximate");

    const noCommon = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", scope: "chunk", operator: "AND" }));
    assert.deepEqual(noCommon.results.map((r) => r.law_id), ["r122RG00000032"]);
    assert.equal(noCommon.index_caps.pages_fetch_limit, 46);
    assert.equal(noCommon.index_caps.candidate_scan_limit, 300);
    assert.equal(noCommon.index_caps.snippet_window_chars, 280);

    const zeroAnd = toolText(await callTool("search_laws_by_content", { query: "公募 3600万円", operator: "AND", scope: "chunk" }));
    assert.equal(zeroAnd.count, 0);
    assert.equal(zeroAnd.completeness, "complete");
    assert.ok(zeroAnd.filtered_out_no_term + zeroAnd.filtered_out_exact >= 1);
  } finally {
    restore();
  }
});

test("scope and group_by combinations (law/AND, law/OR, chunk/group_by=law) and resource propagation", async () => {
  const { impl } = pagesRouter(CORPUS_ROUTES);
  const restore = mockFetch(impl);
  try {
    const lawAnd = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", scope: "law", operator: "AND" }));
    assert.deepEqual(lawAnd.results.map((r) => r.law_id).sort(), ["r122RG00000032", "r122RG00000034"]);
    const twoProof = lawAnd.results.find((r) => r.law_id === "r122RG00000034");
    assert.equal(twoProof.matches.length, 2);
    assert.deepEqual(twoProof.matched_terms.sort(), ["600万円", "随意契約"]);
    assert.equal(lawAnd.group_by, "law");

    const lawOr = toolText(await callTool("search_laws_by_content", { query: "随意契約 600万円", scope: "law", operator: "OR", limit: 20 }));
    const partialLaw = lawOr.results.find((r) => r.law_id === "r122RG00000033");
    assert.ok(partialLaw);
    assert.deepEqual(partialLaw.matched_terms, ["随意契約"]);
    assert.deepEqual(partialLaw.unmatched_terms, ["600万円"]);

    const chunkGroupedByLaw = toolText(
      await callTool("search_laws_by_content", { query: "随意契約 600万円", scope: "chunk", group_by: "law" })
    );
    assert.equal(chunkGroupedByLaw.scope, "chunk");
    assert.equal(chunkGroupedByLaw.group_by, "law");
    assert.deepEqual(chunkGroupedByLaw.results.map((r) => r.law_id), ["r122RG00000032"]);

    const appResource = toolText(await callTool("search_laws_by_content", { query: "別表第2 随意契約", scope: "law" }));
    assert.equal(appResource.count, 1);
    assert.equal(appResource.results[0].kind, "appendix_table");
    assert.equal(appResource.results[0].content_status, "external_resource_only");
    assert.equal(appResource.results[0].resource?.href, "honbun_2.rtf");
    assert.equal(appResource.results[0].matches.length, 2);

    const headingOnly = toolText(await callTool("search_laws_by_content", { query: "別表第4" }));
    assert.equal(headingOnly.results[0].snippet, "別表第4(第21条関係)");
    assert.equal(headingOnly.results[0].resource?.href, "word/r122FG00002360.rtf");
  } finally {
    restore();
  }
});

test("NFKC expansion, full-width digits, punctuation symbols, and label boundary preserve highlight offsets (#78/#99/#100)", async () => {
  const nfkcChunks = [
    { i: 0, law_id: "r122RG00000051", title: "記号規則", label: "第2条", kind: "article", text: "㍻元年の規定により、第2条 対象とする。" },
    { i: 1, law_id: "r122RG00000052", title: "交付要綱", label: "第7条", kind: "article", text: "交付額は６００万円とする。" },
    { i: 2, law_id: "r122RG00000053", title: "記号規則2", label: "第3条", kind: "article", text: "㈱東松島および⑴号は、⒈の例による。" },
    { i: 3, law_id: "r122RG00000054", title: "事務規程", label: "別表第1", kind: "appendix_table", text: "別表第10(第2条関係)" },
  ];
  const { impl } = pagesRouter(buildSearchRoutes(nfkcChunks));
  const restore = mockFetch(impl);
  try {
    const era = toolText(await callTool("search_laws_by_content", { query: "第2条" }));
    const [hl1] = era.results[0].highlights;
    assert.equal(era.results[0].snippet.slice(hl1.start, hl1.end), "第2条");

    const fw = toolText(await callTool("search_laws_by_content", { query: "600万円" }));
    const [hl2] = fw.results[0].highlights;
    assert.equal(fw.results[0].snippet.slice(hl2.start, hl2.end), "６００万円");

    for (const [query, expected] of [["㈱東松島", "㈱東松島"], ["株東松島", "㈱東松島"], ["⑴号", "⑴号"], ["1号", "⑴号"]]) {
      const sym = toolText(await callTool("search_laws_by_content", { query, exact: true }));
      assert.equal(sym.count, 1, query);
      const [hl] = sym.results[0].highlights;
      assert.equal(sym.results[0].snippet.slice(hl.start, hl.end), expected, query);
    }

    const labelBoundary = toolText(await callTool("search_laws_by_content", { query: "別表第10" }));
    assert.ok(labelBoundary.results[0].snippet.includes("別表第10(第2条関係)"));
    assert.ok(!labelBoundary.results[0].snippet.includes("別表第1 0"));
  } finally {
    restore();
  }
});

test("law_id scoped search searches only that ordinance, preserves resource/unit_id, and avoids duplicate labels", async () => {
  const { impl, requested } = pagesRouter({
    "/api/laws/r122RG00000070.json": SCOPE_LAW,
    "/api/laws/r122RG00000002.json": SAMPLE_LAW,
  });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("search_laws_by_content", { query: "手数料", law_id: "r122RG00000070", limit: 5 }));
    assert.ok(payload.count > 0);
    assert.equal(payload.pages_fetches, 1);
    assert.equal(payload.scope, "chunk");
    assert.equal(payload.group_by, "chunk");
    assert.equal(payload.content_current_date, "令和8年6月26日");
    assert.ok(payload.results.some((row) => row.kind === "appendix_table"));
    assert.ok(payload.results.some((row) => row.unit_id === "r122RG00000070#article-第2条"));
    assert.ok(!requested.some((url) => url.includes("/api/search/")));

    const scopedLaw = toolText(
      await callTool("search_laws_by_content", { query: "別表第2", law_id: "r122RG00000070", scope: "law" })
    );
    const row = scopedLaw.results[0];
    assert.equal(row.content_status, "external_resource_only");
    assert.equal(row.resource?.href, "honbun_2.rtf");
    assert.equal(row.matches[0].resource?.href, "honbun_2.rtf");

    const headingDedup = toolText(await callTool("search_laws_by_content", { query: "別表第2", law_id: "r122RG00000002" }));
    const appRow = headingDedup.results.find((item) => item.kind === "appendix_table");
    assert.equal(appRow.snippet.match(/別表第2/g).length, 1);

    const unknown = toolText(await callTool("search_laws_by_content", { query: "手数料", law_id: "r999RG99999999" }));
    assert.equal(unknown.found, false);
    assert.equal(unknown.count, 0);
  } finally {
    restore();
  }
});

test("completeness becomes partial when candidate_scan_limit or pages_fetch_budget is reached", async () => {
  const scanChunks = Array.from({ length: 305 }, (_, i) => ({
    i,
    law_id: "r122RG00000001",
    title: "大量規定条例",
    label: `第${i + 1}条`,
    kind: "article",
    text: `第${i + 1}条 監査の実施基準に関する事項。`,
  }));
  const restoreScan = mockFetch(pagesRouter(buildSearchRoutes(scanChunks)).impl);
  try {
    const scanLimited = toolText(await callTool("search_laws_by_content", { query: "監査", limit: 10 }));
    assert.equal(scanLimited.candidates_examined, 300);
    assert.equal(scanLimited.completeness, "partial");
    assert.equal(scanLimited.truncated, true);
    assert.ok(scanLimited.truncation_reasons.includes("candidate_scan_limit"));
  } finally {
    restoreScan();
  }

  const budgetChunks = Array.from({ length: 50 }, (_, i) => ({
    i,
    law_id: `r122RG${String(i).padStart(8, "0")}`,
    title: `条例${i}`,
    label: "第1条",
    kind: "article",
    text: "随意契約の締結手続に関する規定。",
  }));
  const restoreBudget = mockFetch(pagesRouter(buildSearchRoutes(budgetChunks, {}, { chunkShardSize: 1 })).impl);
  try {
    const budgetLimited = toolText(
      await callTool("search_laws_by_content", { query: "随意契約 存在しない語", operator: "AND", scope: "chunk" })
    );
    assert.equal(budgetLimited.pages_fetches, 46);
    assert.equal(budgetLimited.completeness, "partial");
    assert.equal(budgetLimited.truncated, true);
    assert.ok(budgetLimited.truncation_reasons.includes("pages_fetch_budget"));
  } finally {
    restoreBudget();
  }
});
