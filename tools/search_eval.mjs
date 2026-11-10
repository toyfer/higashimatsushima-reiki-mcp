import { webcrypto } from "node:crypto";
globalThis.crypto ??= webcrypto;
import { readFile } from "node:fs/promises";
import worker from "../worker/src/index.js";

// Golden-set evaluation for search algorithm changes (issue #55).
// Usage: node tools/search_eval.mjs [fixtures.json]
// Requires network access to the live Pages index. Prints per-case verdicts
// and a summary of exact-match violations, fetches and latency.

const env = {
  AUTH_TOKEN: "local-eval",
  PAGES_BASE: process.env.PAGES_BASE || "https://toyfer.github.io/higashimatsushima-reiki-mcp",
};
const fixturePath = process.argv[2] || new URL("../tests/fixtures/search_golden.json", import.meta.url);
const golden = JSON.parse(await readFile(fixturePath, "utf8"));

async function call(name, arguments_) {
  const started = Date.now();
  const response = await worker.fetch(
    new Request("https://eval.local/mcp", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer local-eval" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: arguments_ } }),
    }),
    env
  );
  const body = await response.json();
  return { body, ms: Date.now() - started };
}

let failures = 0;
for (const testCase of golden.cases) {
  const { body, ms } = await call("search_laws_by_content", { query: testCase.query, ...(testCase.args || {}) });
  if (testCase.expect_error) {
    const isError = Boolean(body.error) || body.result?.isError;
    console.log(`${isError ? "PASS" : "FAIL"} ${testCase.name}: expected error, got ${isError ? "error" : "ok"} (${ms}ms)`);
    if (!isError) failures += 1;
    continue;
  }
  if (body.error || body.result?.isError) {
    console.log(`FAIL ${testCase.name}: unexpected error ${body.error?.message} (${ms}ms)`);
    failures += 1;
    continue;
  }
  const payload = JSON.parse(body.result.content[0].text);
  const ids = new Set((payload.results || []).map((row) => row.law_id));
  const missing = (testCase.must_include || []).filter((id) => !ids.has(id));
  const leaked = (testCase.must_exclude || []).filter((id) => ids.has(id));
  const exactViolations = (payload.results || []).filter((row) => row.match_type === "exact" && !(row.highlights || []).length).length;
  const verdict = missing.length === 0 && leaked.length === 0 && exactViolations === 0 ? "PASS" : "FAIL";
  if (verdict === "FAIL") failures += 1;
  console.log(
    `${verdict} ${testCase.name}: count=${payload.count} completeness=${payload.completeness} fetches=${payload.pages_fetches} ms=${ms} ` +
      `missing=[${missing.join(",")}] leaked=[${leaked.join(",")}] exact_violations=${exactViolations}`
  );
}
console.log(failures === 0 ? "ALL PASS" : `${failures} FAILURES`);
process.exit(failures === 0 ? 0 : 1);
