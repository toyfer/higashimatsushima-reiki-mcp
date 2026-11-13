import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { callTool, mockFetch, toolText } from "./helpers.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../..");

function buildApiWithPython(outDir) {
  const script = `
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(${JSON.stringify(REPO_ROOT)}) / "scripts"))
from parse_honbun import parse_honbun
from search_index import build_search_index

def page(title, body):
    return f"<!DOCTYPE html><html><head><title>{title}</title></head><body><div id='primary'>{body}<!-- /本文 --></div></body></html>"

fixtures = [
    ("r122RG00000494", "https://example.test/494.html", page("契約特例要綱", """
        <p>第1条 随意契約は600万円以下の額で締結できる。</p>
        <p>第2条 ㍻元年の規定により、交付額は６００万円とする。</p>
        <p>附則</p><p>公布の日から施行する。</p>
    """)),
    ("r122RG00000524", "https://example.test/524.html", page("評価基準規則", """
        <p>第1条 評価基準は別表のとおりとする。</p>
        <p>別表第1 評価点600点、契約額3,600万円を基準とする。</p>
    """)),
    ("r122RG00001013", "https://example.test/1013.html", page("災害対策本部運営要綱", """
        <div class="toc"><p class="title">目次</p></div>
        <div class="in-chapter"><p class="toc_item-chapter"><span class="num">第1章</span> <span class="title">総則</span>(第1条)</p></div>
        <div class="chapter"><p class="num"><span class="num">第1章</span> <span class="title">総則</span></p></div>
        <p>第5節 鉱産税 削除</p>
        <p>第1条 本部を置く。</p>
        <p>別表第1(第1条関係) 被害認定基準</p><p>1 全壊 50パーセント以上</p>
        <div class="form_section"><p class="num"><a href="#" onClick="fileDownloadAction2('honbun_1.rtf')"><span>様式第1号</span><span>(第14条関係)</span></a></p></div>
        <div class="form_section"><p class="num"><a href="#" onClick="fileDownloadAction2('honbun_2.rtf')"><span>別表第2</span><span>(第5条関係)</span></a></p></div>
        <div id="e1" class="xref_frame cm"><p><img src="/reiki/honbun_1.png"></p></div>
        <div id="e2" class="xref_frame cm"><p><img src="/reiki/honbun_2.png"></p></div>
    """)),
]

out = Path(${JSON.stringify(outDir)})
(out / "laws").mkdir(parents=True, exist_ok=True)
laws = []
for law_id, url, html in fixtures:
    parsed = parse_honbun(html, law_id=law_id, source_url=url)
    parsed["data_version"] = "py-contract-v1"
    parsed["content_current_date"] = "令和8年6月26日"
    (out / "laws" / f"{law_id}.json").write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    laws.append(parsed)

manifest = build_search_index(laws).write(out / "search", data_version="py-contract-v1", generated_at_utc="2026-11-13T00:00:00Z")
title_index = {
    "data_version": "py-contract-v1",
    "laws": [
        {
            "id": l["id"], "title": l["title"], "ordinance_number": l["ordinance_number"],
            "classification": l["classification"], "enacted_date": l["enacted_date"],
            "article_count": l["article_count"], "source_url": l["source_url"],
        }
        for l in laws
    ],
}
(out / "search" / "title-index.json").write_text(json.dumps(title_index, ensure_ascii=False), encoding="utf-8")
health = {
    "ok": True, "law_count": len(laws), "expected_count": len(laws),
    "failure_count": 0, "data_version": "py-contract-v1", "search_chunk_count": manifest["chunk_count"],
}
(out / "health.json").write_text(json.dumps(health, ensure_ascii=False), encoding="utf-8")
(out / "meta.json").write_text(json.dumps(health, ensure_ascii=False), encoding="utf-8")
`;
  execFileSync("python3", ["-c", script], { stdio: "pipe" });
}

function serveApiDir(apiDir) {
  return async (input) => {
    const pathname = new URL(typeof input === "string" ? input : input.url).pathname;
    const rel = pathname.replace(/^\/higashimatsushima-reiki-mcp\/api\//, "").replace(/^\/api\//, "");
    const target = path.join(apiDir, rel);
    if (!fs.existsSync(target) || fs.statSync(target).isDirectory()) {
      return new Response("not found", { status: 404 });
    }
    return new Response(fs.readFileSync(target, "utf8"), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
}

test("Python parse_honbun + search_index output works end-to-end in the Worker", async (t) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "reiki-contract-"));
  t.after(() => fs.rmSync(tmpDir, { recursive: true, force: true }));
  buildApiWithPython(tmpDir);

  const restore = mockFetch(serveApiDir(tmpDir));
  try {
    const status = toolText(await callTool("reiki_status", {}));
    assert.equal(status.search.published, true);
    assert.equal(status.search.data_version, "py-contract-v1");

    const toc = toolText(await callTool("get_toc", { law_id: "r122RG00001013" }));
    assert.deepEqual(toc.chapters.map((c) => c.text), ["第1章 総則"]);
    assert.deepEqual(toc.deleted_headings, ["第5節 鉱産税 削除"]);

    const inlineTable = toolText(await callTool("get_unit", { law_id: "r122RG00001013", kind: "appendix_table", n: 1 }));
    assert.equal(inlineTable.content_status, "complete");
    assert.equal(inlineTable.resource, null);

    const extTable = toolText(await callTool("get_unit", { law_id: "r122RG00001013", kind: "appendix_table", n: 2 }));
    assert.equal(extTable.content_status, "external_resource_only");
    assert.equal(extTable.resource?.href, "honbun_2.rtf");

    const exact = toolText(await callTool("search_laws_by_content", { query: "600万円" }));
    const hitIds = exact.results.map((r) => r.law_id);
    assert.deepEqual(hitIds, ["r122RG00000494", "r122RG00000494"]);
    assert.ok(!hitIds.includes("r122RG00000524"));

    const fullwidthHit = exact.results.find((r) => r.label === "第2条");
    assert.ok(fullwidthHit, JSON.stringify(exact.results));
    const [hl] = fullwidthHit.highlights;
    assert.equal(fullwidthHit.snippet.slice(hl.start, hl.end), "６００万円");

    const scoped = toolText(await callTool("search_laws_by_content", { query: "別表第2 本部", law_id: "r122RG00001013", scope: "law" }));
    assert.equal(scoped.count, 1);
    assert.equal(scoped.results[0].matches.length, 2);
    assert.ok(scoped.results[0].matches.some((m) => m.resource?.href === "honbun_2.rtf"));
  } finally {
    restore();
  }
});
