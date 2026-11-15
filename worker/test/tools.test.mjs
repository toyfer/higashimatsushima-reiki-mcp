import test from "node:test";
import assert from "node:assert/strict";
import { SAMPLE_LAW, TITLE_INDEX, callTool, mockFetch, pagesRouter, toolText } from "./helpers.mjs";

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

test("reiki_status reports whether the search index is published", async () => {
  const { impl } = pagesRouter({
    "/api/meta.json": { data_version: "fx", law_count: 1 },
    "/api/health.json": { ok: true, law_count: 1, expected_count: 1, failure_count: 0 },
    "/api/search/manifest.json": {
      data_version: "fx",
      kind: "bigram-tfidf",
      law_count: 1,
      chunk_count: 2,
      files: { chunks: ["chunks-000.json"], postings: ["postings-00.json"] },
    },
  });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("reiki_status", {}));
    assert.equal(payload.search.published, true);
    assert.equal(payload.search.chunk_count, 2);
  } finally {
    restore();
  }
});

test("search_laws_by_title ranks exact matches, normalizes NFKC/spaces, strips body_text, and honors limit", async () => {
  const { impl } = pagesRouter({ "/api/search/title-index.json": TITLE_INDEX });
  const restore = mockFetch(impl);
  try {
    const exact = toolText(await callTool("search_laws_by_title", { query: "東松島市手数料条例", limit: 5 }));
    assert.deepEqual(exact.laws.map((law) => law.id), ["r122RG00000001", "r122RG00000003"]);
    assert.equal(exact.count, 2);
    assert.equal(exact.data_version, "fx");
    assert.equal(exact.laws[0].article_count, 6);
    assert.equal(exact.laws[0].source_url, "https://example.invalid/1.html");
    assert.ok(!("body_text" in exact.laws[0]));
    assert.ok(!JSON.stringify(exact).includes("xxxxxxxxxx"));

    const limited = toolText(await callTool("search_laws_by_title", { query: "条例", limit: 2 }));
    assert.equal(limited.laws.length, 2);

    const empty = toolText(await callTool("search_laws_by_title", { query: "存在しない条例名" }));
    assert.equal(empty.count, 0);
    assert.deepEqual(empty.laws, []);

    const nfkc = toolText(await callTool("search_laws_by_title", { query: "条例第１０号" }));
    assert.deepEqual(nfkc.laws.map((law) => law.id), ["r122RG00000001"]);

    const spaced = toolText(await callTool("search_laws_by_title", { query: "東松島 手数料" }));
    assert.deepEqual(spaced.laws.map((law) => law.id), ["r122RG00000001", "r122RG00000003"]);
    const ideographic = toolText(await callTool("search_laws_by_title", { query: "東松島　税" }));
    assert.deepEqual(ideographic.laws.map((law) => law.id), ["r122RG00000002"]);

    const partial = toolText(await callTool("search_laws_by_title", { query: "東松島 存在しない" }));
    assert.equal(partial.count, 0);
  } finally {
    restore();
  }
});

test("search_laws_by_title reports a missing title index instead of empty results", async () => {
  const restore = mockFetch(async () => new Response("not found", { status: 404 }));
  try {
    const body = await callTool("search_laws_by_title", { query: "条例" });
    assert.equal(body.result.isError, true);
    assert.match(body.result.content[0].text, /title index/i);
  } finally {
    restore();
  }
});

test("get_law normalizes id case and distinguishes missing law from outage", async () => {
  const { impl, requested } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const hit = toolText(await callTool("get_law", { law_id: "R122RG00000002" }));
    assert.equal(hit.id, "r122RG00000002");
    assert.equal(hit.title, SAMPLE_LAW.title);
    assert.ok(requested.some((url) => url.endsWith("/api/laws/r122RG00000002.json")), requested.join(","));

    const missing = toolText(await callTool("get_law", { law_id: "r122RG99999999" }));
    assert.equal(missing.found, false);
    assert.equal(missing.reason, "not_found");
  } finally {
    restore();
  }
});

test("get_article handles whole articles, paragraphs, items, version metadata, and missing labels", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const article = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第2条" }));
    assert.equal(article.source_url, SAMPLE_LAW.source_url);
    assert.equal(article.title, SAMPLE_LAW.title);
    assert.equal(article.data_version, "fx");
    assert.equal(article.content_current_date, "令和8年6月26日");
    assert.deepEqual(article.articles.map((a) => a.label), ["第2条"]);

    const missingArticle = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第99条" }));
    assert.equal(missingArticle.found, false);
    assert.equal(missingArticle.source_url, SAMPLE_LAW.source_url);
    assert.equal(missingArticle.available_labels, "第1条, 第2条");
    assert.equal(missingArticle.available_labels_truncated, false);

    for (const variant of ["第１条", "1", "第 一 条"]) {
      const normalized = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: variant }));
      assert.equal(normalized.found, true, variant);
      assert.equal(normalized.article_label, "第1条", variant);
      assert.equal(normalized.requested_article_label, variant, variant);
    }
    const withText = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条" }));
    assert.ok(withText.articles[0].paragraphs?.length || "text" in withText.articles[0]);
    const light = toolText(
      await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", include_plain_text: false })
    );
    assert.equal(light.found, true);
    assert.ok(light.articles[0].paragraphs.length > 0);
    assert.ok(!("text" in light.articles[0]) || light.articles[0].paragraphs.length === 0);

    const para = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", paragraph: 2 }));
    assert.equal(para.found, true);
    assert.equal(para.paragraph.number, 2);
    assert.equal(para.paragraph.text, "第二項の本文。");
    assert.deepEqual(para.paragraph.items, []);

    const item = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", paragraph: 1, item: 2 }));
    assert.deepEqual(item.paragraph.items, [{ label: "(2)", text: "土曜日" }]);

    const badItem = await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", item: 2 });
    assert.equal(badItem.error.code, -32602);

    const missingPara = toolText(await callTool("get_article", { law_id: "r122RG00000002", article_label: "第1条", paragraph: 9 }));
    assert.equal(missingPara.found, false);
    assert.deepEqual(missingPara.available_paragraphs, [1, 2]);
  } finally {
    restore();
  }
});

test("get_toc lists articles, units, chapters, deleted headings, pagination, and body_text summary", async () => {
  const longHeading = "別表第1（" + "あ".repeat(50) + "関係）";
  const bodyOnly = {
    id: "r122RG00000521",
    title: "東松島市工事請負契約における随意契約ガイドライン",
    data_version: "fx",
    source_url: "https://example.invalid/521.html",
    articles: [],
    appendix_tables: [],
    supplements: [],
    preamble: ["第1 趣旨", "このガイドラインは随意契約の取扱いを定める。"],
    body_text: "第1 趣旨 このガイドラインは随意契約の取扱いを定める。",
  };
  const empty = { ...SAMPLE_LAW, articles: [], preamble: [SAMPLE_LAW.title, ""], body_text: "" };
  const withDeleted = {
    ...SAMPLE_LAW,
    deleted_headings: ["第5節 鉱産税 削除"],
    appendix_tables: [longHeading, "別表第2(第2条関係)"],
  };
  const { impl } = pagesRouter({
    "/api/laws/r122RG00000002.json": withDeleted,
    "/api/laws/r122RG00000521.json": bodyOnly,
    "/api/laws/r122RG00000003.json": empty,
  });
  const restore = mockFetch(impl);
  try {
    const payload = toolText(await callTool("get_toc", { law_id: "r122RG00000002" }));
    assert.equal(payload.source_url, SAMPLE_LAW.source_url);
    assert.equal(payload.appendix_style_count, 0);
    assert.deepEqual(payload.appendix_styles, []);
    assert.equal(payload.article_count, 2);
    assert.equal(payload.supplement_count, 2);
    assert.equal(payload.appendix_table_count, 2);
    assert.deepEqual(payload.articles.map((article) => article.label), ["第1条", "第2条"]);
    assert.deepEqual(payload.supplements, ["附則1", "附則2"]);
    assert.deepEqual(payload.chapters.map((chapter) => chapter.text), ["第1章 総則", "第2章 雑則"]);
    assert.equal(payload.articles[0].chapter, "第1章");
    assert.equal(payload.articles[0].chapter_title, "総則");
    assert.deepEqual(payload.deleted_headings, ["第5節 鉱産税 削除"]);
    assert.equal(payload.appendix_tables[0].length, 40);
    assert.equal(payload.resources.length, 2);
    assert.equal(payload.resources[1].href, "word/r122FG00000002.rtf");
    assert.equal(payload.resources[1].href_url, "https://example.invalid/word/r122FG00000002.rtf");
    assert.equal(payload.resources[1].image_full_url, "https://example.invalid/word/r122FG00000002s.png");
    assert.equal(payload.next_offset, null);

    const paged = toolText(await callTool("get_toc", { law_id: "r122RG00000002", limit: 1 }));
    assert.equal(paged.next_offset, 1);

    const bodyPayload = toolText(await callTool("get_toc", { law_id: "r122RG00000521" }));
    assert.equal(bodyPayload.article_count, 0);
    assert.equal(bodyPayload.has_body_text, true);
    assert.equal(bodyPayload.body_text_chars, bodyOnly.body_text.length);
    assert.equal(bodyPayload.preamble_count, 2);
    assert.match(bodyPayload.body_text_preview, /^第1 趣旨/);

    const emptyPayload = toolText(await callTool("get_toc", { law_id: "r122RG00000003" }));
    assert.equal(emptyPayload.article_count, 0);
    assert.equal(emptyPayload.has_body_text, false);
    assert.equal(emptyPayload.body_text_chars, 0);
    assert.equal(emptyPayload.preamble_count, 0);
    assert.equal(emptyPayload.body_text_preview, "");
  } finally {
    restore();
  }
});

test("get_unit returns appendix/supplement units, accepts aliases, and resolves explicit vs legacy resources", async () => {
  const mappedLaw = {
    ...SAMPLE_LAW,
    id: "r122RG00000010",
    appendix_tables: ["別表第1(第3条関係) 被害認定基準\n1 全壊 50パーセント以上", "別表第2(第5条関係)"],
    resources: [FORM_RESOURCE, TABLE_RESOURCE],
    appendix_table_resource_index: [null, 1],
  };
  const legacyLaw = {
    ...SAMPLE_LAW,
    id: "r122RG00000011",
    appendix_tables: ["別表第1(第2条関係)"],
    resources: [{ ...TABLE_RESOURCE, label: "別表第1(第2条関係)", table_number: 1, seq: 1 }],
  };
  const brokenMappingLaw = {
    ...SAMPLE_LAW,
    id: "r122RG00000012",
    appendix_tables: ["別表第3(第9条関係)"],
    resources: [TABLE_RESOURCE],
    appendix_table_resource_index: [7],
  };
  const { impl } = pagesRouter({
    "/api/laws/r122RG00000002.json": SAMPLE_LAW,
    "/api/laws/r122RG00000010.json": mappedLaw,
    "/api/laws/r122RG00000011.json": legacyLaw,
    "/api/laws/r122RG00000012.json": brokenMappingLaw,
  });
  const restore = mockFetch(impl);
  try {
    const table = toolText(await callTool("get_unit", { law_id: "r122RG00000002", kind: "appendix_table", n: 2 }));
    assert.equal(table.resource.href_url, "https://example.invalid/word/r122FG00000002.rtf");
    assert.equal(table.found, true);
    assert.equal(table.unit_id, "r122RG00000002#appendix_table-2");
    assert.equal(table.content_status, "external_resource_only");
    assert.equal(table.resource.href, "word/r122FG00000002.rtf");

    const byAlias = toolText(await callTool("get_unit", { law_id: "r122RG00000002", kind: "beppyo", n: 1 }));
    assert.equal(byAlias.content_status, "complete");

    const supplement = toolText(await callTool("get_unit", { law_id: "r122RG00000002", kind: "suppl", n: 2 }));
    assert.equal(supplement.label, "附則2");
    assert.match(supplement.text, /改正規定/);

    const missing = toolText(await callTool("get_unit", { law_id: "r122RG00000002", kind: "supplement", n: 9 }));
    assert.equal(missing.found, false);
    assert.deepEqual(missing.available_n, [1, 2]);

    const mappedExt = toolText(await callTool("get_unit", { law_id: mappedLaw.id, kind: "appendix_table", n: 2 }));
    assert.equal(mappedExt.resource?.href, "honbun_2.rtf");
    assert.equal(mappedExt.content_status, "external_resource_only");

    const mappedInline = toolText(await callTool("get_unit", { law_id: mappedLaw.id, kind: "appendix_table", n: 1 }));
    assert.equal(mappedInline.resource, null);
    assert.equal(mappedInline.content_status, "complete");
    assert.ok(mappedInline.text.includes("全壊"));

    const legacy = toolText(await callTool("get_unit", { law_id: legacyLaw.id, kind: "appendix_table", n: 1 }));
    assert.equal(legacy.resource?.label, "別表第1(第2条関係)");
    assert.equal(legacy.content_status, "external_resource_only");

    const outOfRange = toolText(await callTool("get_unit", { law_id: brokenMappingLaw.id, kind: "appendix_table", n: 1 }));
    assert.equal(outOfRange.resource, null);
    assert.equal(outOfRange.content_status, "complete");
  } finally {
    restore();
  }
});

test("get_toc/get_unit expose appendix styles with resolved form resources (#115)", async () => {
  const styleLaw = {
    ...SAMPLE_LAW,
    id: "r122RG00000020",
    source_url: "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_honbun/r122RG00000020.html",
    appendix_styles: ["様式第1号(第8条関係)", "様式第2号(第9条関係)\n申請者氏名"],
    resources: [
      { label: "様式第1号(第8条関係)", kind: "form", href: "word/form1.rtf", image_url: "word/form1s.png" },
      { label: "様式第2号(第9条関係)", kind: "form", href: "word/form2.rtf", image_url: "" },
    ],
  };
  const { impl } = pagesRouter({ "/api/laws/r122RG00000020.json": styleLaw });
  const restore = mockFetch(impl);
  try {
    const toc = toolText(await callTool("get_toc", { law_id: styleLaw.id }));
    assert.equal(toc.appendix_style_count, 2);
    assert.deepEqual(toc.appendix_styles, ["様式第1号(第8条関係)", "様式第2号(第9条関係)"]);

    const first = toolText(await callTool("get_unit", { law_id: styleLaw.id, kind: "style", n: 1 }));
    assert.equal(first.kind, "appendix_style");
    assert.equal(first.unit_id, "r122RG00000020#appendix_style-1");
    assert.equal(first.content_status, "external_resource_only");
    assert.equal(first.resource.href_url, "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_honbun/word/form1.rtf");
    assert.equal(first.resource.image_full_url, "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_honbun/word/form1s.png");

    const second = toolText(await callTool("get_unit", { law_id: styleLaw.id, kind: "appendix_style", n: 2 }));
    assert.equal(second.content_status, "complete");
    assert.match(second.text, /申請者氏名/);

    const missing = toolText(await callTool("get_unit", { law_id: styleLaw.id, kind: "form", n: 9 }));
    assert.equal(missing.found, false);
    assert.deepEqual(missing.available_n, [1, 2]);
  } finally {
    restore();
  }
});

test("get_article truncates a long available_labels list and points to get_toc (#115)", async () => {
  const many = {
    ...SAMPLE_LAW,
    id: "r122RG00000021",
    articles: Array.from({ length: 30 }, (_, i) => ({
      label: `第${i + 1}条`,
      heading: "",
      paragraphs: [{ number: 1, text: "本文。", items: [] }],
    })),
  };
  const { impl } = pagesRouter({ "/api/laws/r122RG00000021.json": many });
  const restore = mockFetch(impl);
  try {
    const missing = toolText(await callTool("get_article", { law_id: many.id, article_label: "第99条" }));
    assert.equal(missing.found, false);
    assert.equal(missing.available_labels_truncated, true);
    assert.equal(missing.available_label_count, 30);
    assert.match(missing.available_labels, /30 labels total/);
    assert.match(missing.available_labels_hint, /get_toc/);
    assert.ok(missing.available_labels.length < 200);
  } finally {
    restore();
  }
});

test("asof is rejected instead of silently returning the current version", async () => {
  const { impl } = pagesRouter({ "/api/laws/r122RG00000002.json": SAMPLE_LAW });
  const restore = mockFetch(impl);
  try {
    const body = await callTool("get_law", { law_id: "r122RG00000002", asof: "2020-04-01" });
    assert.equal(body.error.code, -32602);
    assert.match(body.error.message, /asof is not supported/);
  } finally {
    restore();
  }
});
