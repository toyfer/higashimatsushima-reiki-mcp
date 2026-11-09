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
| `reiki_status` | none | `api/meta.json` and `api/health.json` |
| `search_laws_by_title` | `query`, optional `limit` | `api/laws/index.json` |
| `get_law` | `law_id` | `api/laws/{law_id}.json` |
| `get_article` | `law_id`, `article_label` | `api/laws/{law_id}.json` |

Law IDs must match `^r\d+RG\d+$`, for example `r122RG00000002`. Invalid IDs are rejected before any fetch, so the endpoint cannot be used to probe arbitrary paths on the Pages host.

Tool results are returned as MCP text content containing pretty-printed JSON. Unknown methods return JSON-RPC error `-32601`. Unknown tools and invalid arguments return JSON-RPC error `-32602` (protocol error). Failures while executing a tool, such as a GitHub Pages fetch failure, are returned as a normal result with `isError: true`. Requests without an `id` are notifications and never receive a response, including in batches.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PAGES_BASE` | `https://toyfer.github.io/higashimatsushima-reiki-mcp` | Base URL of the published static API, without a trailing slash |

Responses are cached at the edge for 300 seconds through the `cf` fetch options. After a Pages redeploy, allow up to five minutes for the Worker view to converge, or check `api/health.json` directly for the newest `data_version`.

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
