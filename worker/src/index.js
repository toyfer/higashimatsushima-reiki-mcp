const DEFAULT_PAGES_BASE = "https://toyfer.github.io/higashimatsushima-reiki-mcp";
const SAFE_ID_RE = /^r\d+RG\d+$/i;
const CACHE_TTL_SECONDS = 300;
const PROTOCOL_VERSION = "2024-11-05";

function jsonResponse(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
      ...extraHeaders,
    },
  });
}

function textResult(text) {
  return { content: [{ type: "text", text }] };
}

function pagesBase(env) {
  const raw = (env && env.PAGES_BASE) || DEFAULT_PAGES_BASE;
  return String(raw).replace(/\/+$/, "");
}

async function fetchPagesJson(env, path) {
  const url = `${pagesBase(env)}${path}`;
  const response = await fetch(url, {
    headers: { "User-Agent": "higashimatsushima-reiki-mcp-worker/0.1" },
    cf: { cacheTtl: CACHE_TTL_SECONDS, cacheEverything: true },
  });
  if (!response.ok) {
    throw new Error(`Pages fetch failed: ${response.status} ${url}`);
  }
  return response.json();
}

function normalize(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}

function scoreLaw(law, query) {
  const q = normalize(query);
  if (!q) return 0;
  const title = normalize(law.title);
  const number = normalize(law.ordinance_number);
  const lawId = normalize(law.id);
  const classification = normalize(law.classification);
  if (title === q || number === q || lawId === q) return 100;
  if (title.includes(q)) return 80;
  if (number.includes(q) || lawId.includes(q)) return 70;
  if (classification.includes(q)) return 40;
  return 0;
}

async function callTool(env, name, args) {
  const input = args && typeof args === "object" ? args : {};
  if (name === "reiki_status") {
    const [meta, health] = await Promise.all([
      fetchPagesJson(env, "/api/meta.json"),
      fetchPagesJson(env, "/api/health.json"),
    ]);
    return textResult(JSON.stringify({ meta, health }, null, 2));
  }
  if (name === "search_laws_by_title") {
    const query = String(input.query || "").trim();
    if (!query) throw new Error("query is required");
    const limit = Math.min(Math.max(Number(input.limit) || 10, 1), 50);
    const index = await fetchPagesJson(env, "/api/laws/index.json");
    const laws = Array.isArray(index.laws) ? index.laws : [];
    const ranked = laws
      .map((law) => ({ law, score: scoreLaw(law, query) }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || String(a.law.id).localeCompare(String(b.law.id)))
      .slice(0, limit)
      .map((item) => item.law);
    return textResult(JSON.stringify({ query, count: ranked.length, laws: ranked }, null, 2));
  }
  if (name === "get_law") {
    const lawId = String(input.law_id || "").trim();
    if (!SAFE_ID_RE.test(lawId)) throw new Error("law_id must match ^r\\d+RG\\d+$");
    const law = await fetchPagesJson(env, `/api/laws/${lawId}.json`);
    return textResult(JSON.stringify(law, null, 2));
  }
  if (name === "get_article") {
    const lawId = String(input.law_id || "").trim();
    const label = String(input.article_label || "").trim();
    if (!SAFE_ID_RE.test(lawId)) throw new Error("law_id must match ^r\\d+RG\\d+$");
    if (!label) throw new Error("article_label is required");
    const law = await fetchPagesJson(env, `/api/laws/${lawId}.json`);
    const articles = Array.isArray(law.articles) ? law.articles : [];
    const found = articles.filter((article) => article.label === label);
    if (!found.length) {
      const available = articles.map((article) => article.label).join(", ");
      return textResult(JSON.stringify({ law_id: lawId, article_label: label, found: false, available_labels: available }, null, 2));
    }
    return textResult(JSON.stringify({ law_id: lawId, title: law.title, articles: found }, null, 2));
  }
  throw new Error(`Unknown tool: ${name}`);
}

const TOOLS = [
  {
    name: "reiki_status",
    description: "Return the published static API meta and health: generation time, site current date, menu hash, data version, law count and failure count.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "search_laws_by_title",
    description: "Search Higashimatsushima ordinances by title keyword, ordinance number, law ID, or classification fragment. Returns matching laws from the published index.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Title keyword, ordinance number, or law ID fragment" },
        limit: { type: "number", description: "Maximum results, 1 to 50. Default 10." },
      },
      required: ["query"],
      additionalProperties: false,
    },
  },
  {
    name: "get_law",
    description: "Fetch one ordinance in full: articles, paragraphs, items, supplements, appendix tables and history, by law ID such as r122RG00000002.",
    inputSchema: {
      type: "object",
      properties: { law_id: { type: "string", description: "Law ID matching ^r\\d+RG\\d+$" } },
      required: ["law_id"],
      additionalProperties: false,
    },
  },
  {
    name: "get_article",
    description: "Fetch one article of an ordinance by its label such as 第1条 or 第2条の2.",
    inputSchema: {
      type: "object",
      properties: {
        law_id: { type: "string", description: "Law ID matching ^r\\d+RG\\d+$" },
        article_label: { type: "string", description: "Article label such as 第1条" },
      },
      required: ["law_id", "article_label"],
      additionalProperties: false,
    },
  },
];

async function handleMcp(request, env) {
  if (request.method === "GET") {
    return jsonResponse({
      name: "higashimatsushima-reiki-mcp",
      transport: "streamable-http (stateless JSON-RPC over POST)",
      protocolVersion: PROTOCOL_VERSION,
      tools: TOOLS.map((tool) => tool.name),
      pages_base: pagesBase(env),
    });
  }
  if (request.method !== "POST") {
    return jsonResponse({ error: "Method not allowed. Use POST for JSON-RPC." }, 405);
  }
  let payload;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error: body must be JSON" } }, 400);
  }
  const messages = Array.isArray(payload) ? payload : [payload];
  const responses = [];
  for (const message of messages) {
    const id = message && "id" in message ? message.id : null;
    const method = message && message.method;
    const isNotification = !message || !("id" in message);
    try {
      if (method === "initialize") {
        responses.push({
          jsonrpc: "2.0",
          id,
          result: {
            protocolVersion: PROTOCOL_VERSION,
            capabilities: { tools: {} },
            serverInfo: { name: "higashimatsushima-reiki-mcp", version: "0.1.0" },
          },
        });
      } else if (method === "ping") {
        responses.push({ jsonrpc: "2.0", id, result: {} });
      } else if (method === "tools/list") {
        responses.push({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
      } else if (method === "tools/call") {
        const params = (message && message.params) || {};
        const result = await callTool(env, params.name, params.arguments || {});
        responses.push({ jsonrpc: "2.0", id, result });
      } else if (isNotification) {
        continue;
      } else {
        responses.push({ jsonrpc: "2.0", id, error: { code: -32601, message: `Method not found: ${method}` } });
      }
    } catch (error) {
      if (!isNotification) {
        responses.push({
          jsonrpc: "2.0",
          id,
          error: { code: -32000, message: error instanceof Error ? error.message : String(error) },
        });
      }
    }
  }
  if (!responses.length) {
    return new Response(null, { status: 202, headers: { "Access-Control-Allow-Origin": "*" } });
  }
  return jsonResponse(Array.isArray(payload) ? responses : responses[0]);
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
      });
    }
    const url = new URL(request.url);
    try {
      if (url.pathname === "/health") {
        let published = null;
        try {
          published = await fetchPagesJson(env, "/api/health.json");
        } catch (error) {
          published = { error: error instanceof Error ? error.message : String(error) };
        }
        return jsonResponse({ ok: true, service: "higashimatsushima-reiki-mcp", pages_base: pagesBase(env), published });
      }
      if (url.pathname === "/mcp") {
        return handleMcp(request, env || {});
      }
      if (url.pathname === "/") {
        return jsonResponse({
          name: "higashimatsushima-reiki-mcp",
          description: "MCP wrapper for the Higashimatsushima City ordinances static API on GitHub Pages. The city site remains the primary source.",
          endpoints: { mcp: "/mcp", health: "/health" },
          tools: TOOLS.map((tool) => tool.name),
          pages_base: pagesBase(env),
        });
      }
      return jsonResponse({ error: "Not found", endpoints: { mcp: "/mcp", health: "/health" } }, 404);
    } catch (error) {
      return jsonResponse({ error: error instanceof Error ? error.message : String(error) }, 500);
    }
  },
};
