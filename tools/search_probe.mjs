import { webcrypto } from "node:crypto";
globalThis.crypto ??= webcrypto;
import worker from "../worker/src/index.js";

// Repeatable accuracy/cost battery against the live Pages index.
// Usage: node tools/search_probe.mjs
// Requires network access to toyfer.github.io. Records counts, completeness,
// counters and highlights for a fixed set of queries.

const env = {
  AUTH_TOKEN: "local-probe",
  PAGES_BASE: process.env.PAGES_BASE || "https://toyfer.github.io/higashimatsushima-reiki-mcp",
};

async function call(name, arguments_) {
  const started = Date.now();
  const response = await worker.fetch(
    new Request("https://probe.local/mcp", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer local-probe" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: arguments_ } }),
    }),
    env
  );
  const body = await response.json();
  if (body.error) throw new Error(body.error.message);
  return { payload: JSON.parse(body.result.content[0].text), ms: Date.now() - started };
}

const CASES = [
  ["随意契約 600万円", { query: "随意契約 600万円", limit: 5 }],
  ["随意契約 600万円 (law)", { query: "随意契約 600万円", scope: "law", limit: 5 }],
  ["600万円", { query: "600万円", limit: 5 }],
  ["600点", { query: "600点", limit: 5 }],
  ["決裁区分", { query: "決裁区分", limit: 3 }],
  ["下請", { query: "下請", limit: 3 }],
  ["手数料 日曜日 (OR)", { query: "手数料 日曜日", operator: "OR", limit: 3 }],
  ["別表 第2条", { query: "別表 第2条", limit: 3 }],
];

for (const [label, arguments_] of CASES) {
  const { payload, ms } = await call("search_laws_by_content", arguments_);
  console.log(
    `${label} -> count=${payload.count} completeness=${payload.completeness} fetches=${payload.pages_fetches} ` +
      `ms=${ms} examined=${payload.candidates_examined} fe=${payload.filtered_out_exact} fnt=${payload.filtered_out_no_term} ` +
      `reasons=${JSON.stringify(payload.truncation_reasons)}`
  );
  for (const row of payload.results.slice(0, 3)) {
    const highlights = (row.highlights || []).map((item) => `${item.term}@${item.start}-${item.end}:${item.match_type}`).join(",");
    console.log(`    ${row.law_id} ${row.label} ${row.match_type} score=${row.score} hl=[${highlights}]`);
  }
}

const amount = await call("search_laws_by_content", { query: "600万円", limit: 5 });
const ids = new Set(amount.payload.results.map((row) => row.law_id));
console.log(ids.has("r122RG00000524") ? "FAIL: 600万円 returns r122RG00000524 (bigram false positive)" : "OK: 600万円 excludes r122RG00000524");
const points = await call("search_laws_by_content", { query: "600点", limit: 5 });
const pointIds = new Set(points.payload.results.map((row) => row.law_id));
console.log(pointIds.has("r122RG00000524") ? "OK: 600点 returns r122RG00000524" : "FAIL: 600点 does not return r122RG00000524");
