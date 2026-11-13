## Higashimatsushima ordinance static API and MCP foundation

This repository builds a read-only static API for the Higashimatsushima City ordinance pages and prepares it for a remote MCP server on Cloudflare Workers.

Source: Higashimatsushima City ordinance menu at `https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_menu.html`.

The daily checker never loads every ordinance body by default. It first checks the menu page hash and the site current date. Only when the site changes does it rebuild the ordinance URL index. Full body JSON is built separately into `site/api/` and published by GitHub Pages.

## Architecture

| Layer | Role |
|---|---|
| Higashimatsushima City site | Official ordinance HTML. Always treat it as the primary source. |
| GitHub Actions `daily-reiki-check.yml` | Daily menu check, index crawl on change, status commit and issue notifications. |
| GitHub Actions `pages.yml` | Builds static JSON under `site/api/` and deploys `site/` to GitHub Pages. Runs on push, on a weekly schedule and through `workflow_call` from the daily check. |
| GitHub Pages | Static read-only API: `/api/meta.json`, `/api/laws/index.json`, `/api/laws/{law_id}.json`. |
| Cloudflare Worker | Wraps the static API and exposes `/mcp` plus `/health`. |
| MCP client | Calls the Worker endpoint. It does not read GitHub Pages directly. |

## Static API

After a full build and Pages deploy, the public endpoints are:

| Path | Contents |
|---|---|
| `api/meta.json` | Generation time, site current date, menu hash, data version and law count |
| `api/health.json` | Minimal build health: `ok`, `law_count`, `failure_count`, `data_version` |
| `api/laws/index.json` | Ordinance list with title, ordinance number, classification and article count |
| `api/search/title-index.json` | Small title search index for the Worker |
| `api/search/manifest.json` | Keyword body-search index manifest: `bigram-tfidf`, counts and shard files |
| `api/search/chunks-*.json` | Body-search chunks with title, article label, snippet and `source_url` |
| `api/search/postings-*.json` | Bigram TF-IDF postings sharded by term hash |
| `api/laws/{law_id}.json` | One ordinance: articles, paragraphs, items, supplements, appendix tables, `appendix_styles`, `resources`, `appendix_table_resource_index`, history, plus `content_current_date` and `data_version` |

Example law IDs look like `r122RG00000002`.

### Appendix tables and their resources

`resources` is one array that mixes appendix tables and 様式 (style) documents, and the two do not share an order. `appendix_table_resource_index` maps a table's position in `appendix_tables` to its entry in `resources`: `appendix_table_resource_index[0] === 2` means the first appendix table's RTF or thumbnail is `resources[2]`. A table with no external document has `null` there, and the Worker returns `resource: null` instead of borrowing a neighbouring style document (issue #61).

Each `resources[]` entry carries `kind` (`appendix` or `form`), `table_number`, `table_branch` (the 枝番 of `別表第2の3`, otherwise `null`) and `seq`. The Worker relies only on `appendix_table_resource_index`, so an older JSON without the mapping still resolves through the positional lookup.

`appendix_styles` holds the 様式 sections as text, so a style document no longer enters `appendix_tables` as a heading-only table. A heading-only table whose body lives in RTF or PNG is published with `content_status: external_resource_only` and its `resource`, which is how a missing body stays visible instead of being presented as complete text.

### Body search index

`api/search/manifest.json` describes a bigram TF-IDF index built at Pages build time, so the Worker never scores a corpus at request time:

| Field | Meaning |
|---|---|
| `data_version` | Version of the build that produced every posting and chunk shard |
| `chunk_count` / `chunk_shard_size` | Chunks (`chunks-NNN.json`, 500 per shard) |
| `posting_shards` | Number of posting files, sharded by a hash of the term |
| `max_postings_per_term` | 50 |
| `max_postings_per_law_per_term` | 3 |
| `external_resource_chunks` | Chunks whose body is a heading-only appendix table whose text lives in an RTF or PNG resource |
| `external_resource_chars` | Searchable terms those chunks contribute |

Search runs in two stages: postings generate candidates, then each candidate chunk is verified against its full text, which the chunk shard carries as `text`. The verification step is what stops `600点` + `500万円` from satisfying `600万円`, since the four bigrams match without the phrase. `exact: false` keeps those bigram-only hits and labels them `approximate`.

`operator` (`AND`/`OR`) and `scope` (`chunk`/`law`) are explicit: `scope=chunk` requires every term in one chunk, `scope=law` accepts every term somewhere in one ordinance and returns `matches[]` with the evidence chunk per term. Results include `match_type`, `matched_terms`, `unmatched_terms`, and a `snippet` with `highlights`.

Every chunk carries `content_status` (`complete` or `external_resource_only`), and results echo it together with `resource` when an appendix table has an external document. A heading-only table is therefore never returned as if its body had been parsed.

Within one call the Worker spends at most 46 Pages fetches and 300 examined candidates, and the index truncates each term to 50 postings (3 per law per term). Responses report `completeness` (`complete`/`partial`), `filtered_out_exact`, `filtered_out_no_term`, `skipped_per_law`, `truncation_reasons` and `index_caps`, so "no such term" is distinguishable from "a cap was reached".

Measured index size with full chunk text: 57 shards, 32.4 MiB, largest shard 823 KiB (chunk), 632 KiB (posting) for 20,442 chunks.

Queries need at least two searchable characters after NFKC normalisation, because the index stores bigrams only. Passing a `law_id` to the Worker restricts the search to that ordinance by reading only its JSON, so results never include other ordinances.

## Workflows

### Daily check

Runs at 03:17 JST. The workflow file uses UTC cron `17 18 * * *`.

| Input | Meaning |
|---|---|
| `mode=check` | Fetch the menu page. Crawl index pages only when the menu changed. |
| `mode=collect` | Always crawl index pages and rebuild the ordinance URL list. |
| `force_collect=true` | Same crawl trigger for `check` mode. |

### Pages deploy

`pages.yml` runs on pushes that touch `site/**`, the builder scripts, the status file, or the workflow itself. It also runs weekly (`17 19 * * 6`) and is called by `daily-reiki-check.yml` when the city site changed. Those two paths always build the full API, so a merged parser fix reaches Pages without a manual dispatch.

Manual runs expose:

| Input | Meaning |
|---|---|
| `full_build=false` | Build a 5-ordinance sample API and deploy it. Use this first. |
| `full_build=true` | Fetch every ordinance body in `data/status/latest.json` and deploy the full API. |
| `allow_sample_overwrite` | Permit a 5-ordinance sample run to replace a larger published API. Ignored when `full_build=true`. Leave it `false`; the guard skips the sample deploy instead of downgrading the site. |
| `delay_seconds` | Delay between city-site fetches during a full build. Keep the default unless there is a reason to change it. |

Do not run full builds repeatedly against the city site during development.

A full build regenerates every ordinance body and the whole search index, so it also changes `data_version`. Run it after parser or index changes, then let the Worker pick the new version up.

## Local commands

```bash
python3 -m unittest discover -s tests -v
python3 scripts/daily_check.py --mode check
python3 scripts/build_static_api.py --limit 5 --delay 0.1
python3 scripts/build_static_api.py --only-id r122RG00000002 --delay 0.1
python3 scripts/measure_search_index.py
```

## Files

| Path | Purpose |
|---|---|
| `.github/workflows/daily-reiki-check.yml` | Daily schedule, manual dispatch, status commit, change issue and failure issue |
| `.github/workflows/pages.yml` | Static API build and GitHub Pages deployment |
| `scripts/daily_check.py` | Menu check and systematic index collector |
| `scripts/parse_honbun.py` | Ordinance body HTML parser |
| `scripts/build_static_api.py` | Static API builder writing under `site/api/` |
| `scripts/search_index.py` | Bigram TF-IDF body-search index builder |
| `scripts/measure_search_index.py` | Local / CI measurement of search index build cost and size |
| `data/status/latest.json` | Last known menu hash, site current date and ordinance URL list |
| `site/index.html` | Human-readable entry page for the static API |
| `worker/src/index.js` | Stateless MCP Worker over the published static API |
| `worker/test/index.test.mjs` | Worker tests with mocked Pages responses |
| `.github/workflows/deploy-worker.yml` | Worker deploy, published-index precondition, endpoint verification |
| `tests/` | Network-free parser and checker tests |
| `tests/fixtures/search_golden.json` | Golden-set cases for the body search evaluation |
| `tools/search_eval.mjs` | Golden-set run of the Worker against the published index |
| `.github/workflows/search-eval.yml` | Golden-set run after each successful Pages publish |

## Deploy order and verification

The Worker is already implemented under `worker/` and exposes seven MCP tools: `reiki_status`, `search_laws_by_title`, `search_laws_by_content`, `get_law`, `get_article`, `get_toc` and `get_unit`. Tool behaviour, limits and arguments are documented in `worker/README.md`.

Publish Pages before the Worker. A Worker that points at a Pages site without a search index answers `search_laws_by_content` with a Pages 404, which is why `deploy-worker.yml` checks the published index before `wrangler deploy` and then calls the search tool from the deployed endpoint.

```bash
# 1. publish or refresh the index (full build)
#    Pages workflow -> workflow_dispatch
#    full_build=true, allow_sample_overwrite=false, delay_seconds=0.35
# 2. confirm the published index
curl -fsS "https://toyfer.github.io/higashimatsushima-reiki-mcp/api/search/manifest.json"
curl -fsS "https://toyfer.github.io/higashimatsushima-reiki-mcp/api/health.json"
# 3. deploy the Worker (push to worker/** or run the Deploy Worker workflow)
# 4. confirm the deployed endpoint
curl -fsS https://higashimatsushima-reiki-mcp.toys-master.dev/health
```

The Pages workflow also verifies the built `site/api/search` before upload: a missing manifest, a missing shard, or a shard whose `data_version` differs from `health.json` fails the job instead of deploying a half-updated index.

Only the currently published version is served. Historical snapshots are a separate design problem: responses carry `content_current_date` and `data_version`, and the Worker rejects `asof` rather than returning today's text as if it were historical.
