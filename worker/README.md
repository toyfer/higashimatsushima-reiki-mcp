## Higashimatsushima ordinance MCP Worker

This Worker wraps the GitHub Pages static API and exposes it as a stateless MCP endpoint. It holds no database and no copy of the ordinance bodies. Every tool call reads the published JSON on GitHub Pages, so the city site remains the primary source and GitHub Pages remains the published copy.

| Endpoint | Purpose |
|---|---|
| `GET /` | Service description, tool names, and the configured Pages base |
| `GET /health` | Readiness: Worker plus published API. `ok: false` with HTTP 503 when Pages cannot be fetched or the published API reports failures |
| `GET /live` | Liveness only. Always HTTP 200 with `ok: true`; does not fetch Pages |
| `GET /mcp` | Human-readable endpoint description |
| `POST /mcp` | Stateless JSON-RPC for MCP clients |

## Tools

| Tool | Arguments | Reads |
|---|---|---|
| `reiki_status` | none | `api/meta.json`, `api/health.json`, `api/search/manifest.json` |
| `search_laws_by_title` | `query`, optional `limit` | `api/search/title-index.json` |
| `search_laws_by_content` | `query`, optional `limit`, optional `law_id` | `api/search/manifest.json`, `postings-*.json`, `chunks-*.json`; with `law_id`, `api/laws/{law_id}.json` |
| `get_law` | `law_id` | `api/laws/{law_id}.json` |
| `get_article` | `law_id`, `article_label`, optional `paragraph`, optional `item` | `api/laws/{law_id}.json` |
| `get_toc` | `law_id`, optional `offset`, optional `limit` | `api/laws/{law_id}.json` |
| `get_unit` | `law_id`, `kind`, `n` | `api/laws/{law_id}.json` |

Law IDs must match `^r\d+RG\d+$`, for example `r122RG00000002`. Upper and lower case are accepted and normalised to the published spelling (`R122rg00000002` becomes `r122RG00000002`). Invalid IDs are rejected before any fetch, so the endpoint cannot be used to probe arbitrary paths on the Pages host. A well-formed ID that has no published file returns `found: false` with `reason: "not_found"`, which is distinct from a Pages 5xx or network failure (those surface as `isError: true`).

## Tool behaviour worth knowing

`search_laws_by_title` reads the small title index and returns summaries only (`id`, `title`, `ordinance_number`, `classification`, `enacted_date`, `article_count`, `source_url`). It never returns ordinance bodies, so a `limit=50` query stays small. Use `get_law` for the body.

`search_laws_by_content` runs in two stages. The bigram TF-IDF postings generate candidates, then each candidate chunk is verified against its full text, which is published in the chunk shard as `text`. Verification matters: `600万円` is `60` + `00` + `0万` + `万円`, and a chunk containing `600点` and `500万円` holds all four bigrams without containing `600万円`. With `exact: true` (the default) such a chunk is rejected and counted in `filtered_out_exact`.

| Argument | Values | Meaning |
|---|---|---|
| `query` | string | Space-separated terms, each at least 2 searchable characters |
| `limit` | 1-50 | Displayed results, default 10 |
| `law_id` | law ID | Restrict to one ordinance (reads only that JSON, one fetch) |
| `operator` | `AND` (default) / `OR` | How terms combine |
| `scope` | `chunk` (default) / `law` | `chunk`: every term must appear in the same chunk. `law`: every term must appear somewhere in the same ordinance |
| `group_by` | `chunk` / `law` | Collapse results per ordinance; `law` whenever `scope=law` |
| `exact` | `true` (default) / `false` | `false` keeps bigram-only hits and labels them `approximate` |

Each result carries `match_type` (`exact` / `approximate`), `matched_terms`, `unmatched_terms`, a query-aware `snippet` with `highlights: [{term, start, end, match_type}]` (offsets are relative to `snippet`), and `unit_id` when a result maps to an appendix table or supplement. In `scope=law` each result also has `matches[]`, one evidence entry per matched term with its own label, snippet and highlights.

Every response reports `completeness` (`complete` / `partial`) plus `candidates`, `candidates_examined`, `filtered_out_no_term`, `filtered_out_exact`, `skipped_per_law`, `truncation_reasons` and `index_caps`. `partial` means a cap was reached, so a zero-result answer with `completeness: partial` is not proof the corpus lacks the phrase. The index itself keeps at most 50 postings per term and 3 per law per term; `index_caps` echoes those limits and the per-call fetch and scan budgets.

`scope=law` aggregates the candidates the call actually examined. With the default budgets that is complete for most queries, but when `completeness` is `partial` treat law-level absence as unproven.

`get_article` returns the whole article by default. `paragraph=2` returns only that paragraph, and `item=2` (which requires `paragraph`) returns only that item. Missing paragraphs or items return `found: false` with `available_paragraphs` or `available_items` instead of the full ordinance.

`get_toc` lists article labels and headings with `offset` / `limit`, plus `supplement_count`, `appendix_table_count` and their labels. `get_unit` returns one appendix table (`kind=appendix_table`, aliases `beppyo` / `table`) or one supplement (`kind=supplement`, alias `suppl`) with a 1-based `n`, each with a stable `unit_id` such as `r122RG00000070#appendix_table-1`.

Only the currently published version is served. `asof` is accepted by the schema so the request is understood, but it is rejected with `-32602` rather than silently returning today's text as if it were historical. Read `reiki_status` or any law response for `content_current_date` and `data_version`.

## Index versions

Before touching a posting or chunk shard, the Worker reads `manifest.json` and compares each shard's `data_version` with the manifest. A shard that disagrees is refetched with a version query (`?v=<data_version>`) to bypass the edge cache. If it still disagrees, the tool fails with an explicit version-mismatch error instead of joining old postings with new chunks, which would return unrelated ordinances for a chunk number. If `manifest.json` is missing, `search_laws_by_content` returns a tool error naming `full_build=true`; it does not pretend the corpus has no matches.

Tool results are returned as MCP text content containing pretty-printed JSON. Unknown methods return JSON-RPC error `-32601`. Unknown tools and invalid arguments return JSON-RPC error `-32602` (protocol error). Failures while executing a tool, such as a GitHub Pages fetch failure, are returned as a normal result with `isError: true`. Requests without an `id` are notifications and never receive a response, including in batches.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PAGES_BASE` | `https://toyfer.github.io/higashimatsushima-reiki-mcp` | Base URL of the published static API, without a trailing slash |

Responses are cached at the edge for 300 seconds through the `cf` fetch options. After a Pages redeploy, allow up to five minutes for the Worker view to converge, or check `api/health.json` directly for the newest `data_version`.

## Deploy order

Publish Pages first, then the Worker. `deploy-worker.yml` enforces this by checking `api/search/manifest.json` against `api/health.json` before `wrangler deploy`, and it refuses to publish a Worker whose search endpoint would answer with a Pages 404.

```bash
# 1. publish the index (Pages workflow, workflow_dispatch)
#    full_build=true, allow_sample_overwrite=false, delay_seconds=0.35
# 2. confirm the published index
curl -fsS "https://toyfer.github.io/higashimatsushima-reiki-mcp/api/search/manifest.json" | head -20
# 3. deploy the Worker
#    push to worker/** or run the Deploy Worker workflow
```

## Local check

```bash
cd worker
npm install
npm run dev
```

```bash
curl -s http://localhost:8787/health
curl -s http://localhost:8787/mcp
curl -s -X POST http://localhost:8787/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl -s -X POST http://localhost:8787/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"reiki_status","arguments":{}}}'
```

## Deploy

Deployment needs a Cloudflare account and an authenticated Wrangler session. This repository work does not deploy the Worker by itself.

```bash
cd worker
npx wrangler login
npx wrangler deploy
```

After deployment, point the MCP client at `https://<worker-host>/mcp`. `POST /mcp` requires `Authorization: Bearer <AUTH_TOKEN>`. Set the secret once with `wrangler secret put AUTH_TOKEN`. For the first deploy of a new Worker, `wrangler deploy --secrets-file` also works. `GET /`, `GET /live`, `GET /health`, `GET /mcp` and `OPTIONS` stay unauthenticated. Local development uses `worker/.dev.vars` (see `worker/.dev.vars.example`; the real file is git-ignored).

## Auth note

Only `POST /mcp` is authenticated, because the Worker consumes the account's Workers quota while the underlying GitHub Pages data is already public. When `AUTH_TOKEN` is unset (local tests), the check is skipped.
