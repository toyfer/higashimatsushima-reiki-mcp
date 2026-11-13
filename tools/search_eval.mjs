import { webcrypto } from "node:crypto";
globalThis.crypto ??= webcrypto;
import { readFile, writeFile } from "node:fs/promises";
import worker from "../worker/src/index.js";

// Golden-set evaluation for search algorithm changes (issue #55).
// Usage: node tools/search_eval.mjs [fixtures.json]
// Runs the Worker in-process against the published Pages index, so a failing
// case means the current code and the published corpus disagree. Network
// access to Pages is required; there is no offline mode.
// Set SEARCH_EVAL_SUMMARY to also write a markdown summary to that path.

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

function inspect(testCase, payload) {
  const rows = payload.results || [];
  const ids = new Set(rows.map((row) => row.law_id));
  const units = new Set(rows.map((row) => row.unit_id).filter(Boolean));
  const statuses = new Set(rows.map((row) => row.content_status).filter(Boolean));
  const labels = rows.map((row) => row.label || "");
  const problems = [];

  const missing = (testCase.must_include || []).filter((id) => !ids.has(id));
  if (missing.length) problems.push(`missing=[${missing.join(",")}]`);
  const leaked = (testCase.must_exclude || []).filter((id) => ids.has(id));
  if (leaked.length) problems.push(`leaked=[${leaked.join(",")}]`);
  const missingUnits = (testCase.must_include_units || []).filter((unit) => !units.has(unit));
  if (missingUnits.length) problems.push(`missing_units=[${missingUnits.join(",")}]`);
  const leakedUnits = (testCase.must_exclude_units || []).filter((unit) => units.has(unit));
  if (leakedUnits.length) problems.push(`leaked_units=[${leakedUnits.join(",")}]`);
  if (testCase.must_rank_first && rows[0]?.law_id !== testCase.must_rank_first) {
    problems.push(`rank_first=${rows[0]?.law_id || "none"} (expected ${testCase.must_rank_first})`);
  }
  const missingStatus = (testCase.must_include_status || []).filter((status) => !statuses.has(status));
  if (missingStatus.length) problems.push(`missing_status=[${missingStatus.join(",")}]`);
  const missingLabels = (testCase.must_include_labels || []).filter((label) => !labels.some((value) => value.includes(label)));
  if (missingLabels.length) problems.push(`missing_labels=[${missingLabels.join(",")}]`);
  const leakedLabels = (testCase.must_exclude_labels || []).filter((label) => labels.some((value) => value.includes(label)));
  if (leakedLabels.length) problems.push(`leaked_labels=[${leakedLabels.join(",")}]`);
  if (testCase.expect_completeness && payload.completeness !== testCase.expect_completeness) {
    problems.push(`completeness=${payload.completeness} (expected ${testCase.expect_completeness})`);
  }
  if (typeof testCase.max_fetches === "number" && (payload.pages_fetches ?? 0) > testCase.max_fetches) {
    problems.push(`fetches=${payload.pages_fetches} > ${testCase.max_fetches}`);
  }
  const exactViolations = rows.filter((row) => row.match_type === "exact" && !(row.highlights || []).length).length;
  if (exactViolations) problems.push(`exact_without_highlight=${exactViolations}`);
  return problems;
}

const report = [];
let failures = 0;
let totalMs = 0;
let maxFetches = 0;
let maxFetchesCase = "-";
let slowest = 0;
let slowestCase = "-";
let dataVersion = "";

for (const testCase of golden.cases) {
  const { body, ms } = await call("search_laws_by_content", { query: testCase.query, ...(testCase.args || {}) });
  totalMs += ms;
  if (ms > slowest) {
    slowest = ms;
    slowestCase = testCase.name;
  }
  const failed = (detail) => {
    failures += 1;
    console.log(`FAIL ${testCase.name}: ${detail} (${ms}ms)`);
    report.push(`| ${testCase.name} | fail | ${detail} | ${ms} |`);
  };

  if (testCase.expect_error) {
    const isError = Boolean(body.error) || body.result?.isError;
    if (!isError) {
      failed("expected an error, got a result");
      continue;
    }
    console.log(`PASS ${testCase.name}: rejected as expected (${ms}ms)`);
    report.push(`| ${testCase.name} | pass | rejected as expected | ${ms} |`);
    continue;
  }

  if (body.error || body.result?.isError) {
    failed(`unexpected error ${body.error?.message || body.result?.content?.[0]?.text}`);
    continue;
  }

  const payload = JSON.parse(body.result.content[0].text);
  dataVersion ||= payload.data_version || "";
  const fetches = payload.pages_fetches ?? 0;
  if (fetches > maxFetches) {
    maxFetches = fetches;
    maxFetchesCase = testCase.name;
  }
  const problems = inspect(testCase, payload);
  const line = `count=${payload.count} completeness=${payload.completeness} fetches=${fetches} ms=${ms}`;
  if (problems.length) {
    failed(`${line} ${problems.join(" ")}`);
    continue;
  }
  console.log(`PASS ${testCase.name}: ${line}`);
  report.push(`| ${testCase.name} | pass | ${line} | ${ms} |`);
}

const summary = [
  `### Search golden set: ${failures === 0 ? "pass" : `${failures} failed`}`,
  "",
  `- cases: ${golden.cases.length}`,
  `- data_version: ${dataVersion || "unknown"}`,
  `- max pages_fetches: ${maxFetches} (${maxFetchesCase})`,
  `- slowest case: ${slowest}ms (${slowestCase})`,
  `- total: ${totalMs}ms`,
  "",
  "| case | result | detail | ms |",
  "|---|---|---|---|",
  ...report,
].join("\n");

console.log("");
console.log(summary);
console.log(failures === 0 ? "ALL PASS" : `${failures} FAILURES`);
if (process.env.SEARCH_EVAL_SUMMARY) {
  await writeFile(process.env.SEARCH_EVAL_SUMMARY, `${summary}\n`);
}
process.exit(failures === 0 ? 0 : 1);
