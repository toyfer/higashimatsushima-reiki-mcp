## Higashimatsushima ordinance static API and MCP foundation

This repository builds a read-only static API for the Higashimatsushima City ordinance pages and prepares it for a remote MCP server on Cloudflare Workers.

Source: Higashimatsushima City ordinance menu at `https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_menu.html`.

The daily checker never loads every ordinance body by default. It first checks the menu page hash and the site current date. Only when the site changes does it rebuild the ordinance URL index. Full body JSON is built separately into `site/api/` and published by GitHub Pages.

## Architecture

| Layer | Role |
|---|---|
| Higashimatsushima City site | Official ordinance HTML. Always treat it as the primary source. |
| GitHub Actions `daily-reiki-check.yml` | Daily menu check, index crawl on change, status commit and issue notifications. |
| GitHub Actions `pages.yml` | Builds static JSON under `site/api/` and deploys `site/` to GitHub Pages. |
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
| `api/laws/{law_id}.json` | One ordinance: articles, paragraphs, items, supplements, appendix tables and history |

Example law IDs look like `r122RG00000002`.

## Workflows

### Daily check

Runs at 03:17 JST. The workflow file uses UTC cron `17 18 * * *`.

| Input | Meaning |
|---|---|
| `mode=check` | Fetch the menu page. Crawl index pages only when the menu changed. |
| `mode=collect` | Always crawl index pages and rebuild the ordinance URL list. |
| `force_collect=true` | Same crawl trigger for `check` mode. |

### Pages deploy

`pages.yml` runs on pushes that touch `site/**`, the builder scripts, the status file, or the workflow itself.

Manual runs expose:

| Input | Meaning |
|---|---|
| `full_build=false` | Build a 5-ordinance sample API and deploy it. Use this first. |
| `full_build=true` | Fetch every ordinance body in `data/status/latest.json` and deploy the full API. |
| `delay_seconds` | Delay between city-site fetches during a full build. Keep the default unless there is a reason to change it. |

Do not run full builds repeatedly against the city site during development.

## Local commands

```bash
python3 -m unittest discover -s tests -v
python3 scripts/daily_check.py --mode check
python3 scripts/build_static_api.py --limit 5 --delay 0.1
python3 scripts/build_static_api.py --only-id r122RG00000002 --delay 0.1
```

## Files

| Path | Purpose |
|---|---|
| `.github/workflows/daily-reiki-check.yml` | Daily schedule, manual dispatch, status commit, change issue and failure issue |
| `.github/workflows/pages.yml` | Static API build and GitHub Pages deployment |
| `scripts/daily_check.py` | Menu check and systematic index collector |
| `scripts/parse_honbun.py` | Ordinance body HTML parser |
| `scripts/build_static_api.py` | Static API builder writing under `site/api/` |
| `data/status/latest.json` | Last known menu hash, site current date and ordinance URL list |
| `site/index.html` | Human-readable entry page for the static API |
| `tests/` | Network-free parser and checker tests |

## Next step: Cloudflare Worker

After GitHub Pages serves a sample API, add the Worker under `worker/` and deploy it with Wrangler. The Worker should fetch the Pages JSON, cache it, and expose MCP tools such as status, title search, ordinance fetch and article fetch.
