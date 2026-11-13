const DEFAULT_PAGES_BASE = "https://toyfer.github.io/higashimatsushima-reiki-mcp";
const LAW_ID_RE = /^r\d+RG\d+$/i;
const CANONICAL_ID_RE = /^r(\d+)rg(\d+)$/i;
const CACHE_TTL_SECONDS = 300;
const PROTOCOL_VERSION = "2024-11-05";

const POSTING_SHARD_COUNT = 16;
const CHUNK_SHARD_SIZE = 500;
const MAX_RESULTS_PER_LAW = 3;
const MAX_PAGES_FETCHES = 46;
const MAX_CANDIDATES_WALKED = 300;
const MAX_POSTING_SHARDS = 10;
const MIN_QUERY_CHARS = 2;
const SNIPPET_CHARS = 280;
const SNIPPET_WINDOW = SNIPPET_CHARS;
const MIN_SNIPPET_CHARS = 80;
const MAX_SNIPPET_CHARS = 800;

class ProtocolError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ProtocolError";
    this.code = code;
  }
}

class ToolExecutionError extends Error {
  constructor(message) {
    super(message);
    this.name = "ToolExecutionError";
  }
}

class PagesNotFoundError extends ToolExecutionError {
  constructor(url) {
    super(`Pages fetch failed: 404 ${url}`);
    this.name = "PagesNotFoundError";
    this.status = 404;
    this.url = url;
  }
}

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

async function sha256Bytes(value) {
  const buffer = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(value || "")));
  return new Uint8Array(buffer);
}

function bytesEqual(left, right) {
  if (!left || !right || left.length !== right.length) return false;
  if (typeof globalThis.crypto.subtle.timingSafeEqual === "function") return globalThis.crypto.subtle.timingSafeEqual(left, right);
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index];
  return difference === 0;
}

async function bearerOk(authHeader, token) {
  const value = String(authHeader || "");
  if (value.length < "Bearer ".length || value.slice(0, "Bearer ".length).toLowerCase() !== "bearer ") {
    return false;
  }
  const presented = value.slice("Bearer ".length);
  if (!presented) return false;
  const hashes = await Promise.all([sha256Bytes(presented), sha256Bytes(token)]);
  return bytesEqual(hashes[0], hashes[1]);
}

function textResult(text) {
  return { content: [{ type: "text", text }] };
}

function errorTextResult(text) {
  return { content: [{ type: "text", text }], isError: true };
}

function pagesBase(env) {
  const raw = (env && env.PAGES_BASE) || DEFAULT_PAGES_BASE;
  return String(raw).replace(/\/+$/, "");
}

async function fetchPagesJson(env, path, options = {}) {
  const suffix = options.cacheBust ? `${path.includes("?") ? "&" : "?"}v=${encodeURIComponent(options.cacheBust)}` : "";
  const url = `${pagesBase(env)}${path}${suffix}`;
  let response;
  try {
    response = await fetch(url, {
      headers: { "User-Agent": "higashimatsushima-reiki-mcp-worker/0.2" },
      cf: { cacheTtl: CACHE_TTL_SECONDS, cacheEverything: true },
    });
  } catch (error) {
    throw new ToolExecutionError(`Pages fetch failed: network ${error instanceof Error ? error.message : String(error)} ${url}`);
  }
  if (response.status === 404) {
    if (options.allowNotFound) return null;
    throw new PagesNotFoundError(url);
  }
  if (!response.ok) {
    throw new ToolExecutionError(`Pages fetch failed: ${response.status} ${url}`);
  }
  try {
    return await response.json();
  } catch {
    throw new ToolExecutionError(`Pages fetch failed: invalid JSON ${url}`);
  }
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

function fnv1a32(value) {
  let result = 2166136261;
  for (const char of String(value)) {
    result ^= char.codePointAt(0);
    result = Math.imul(result, 16777619) >>> 0;
  }
  return result >>> 0;
}

function normalizeSearchText(value) {
  return String(value || "").normalize("NFKC").toLowerCase();
}

function searchableText(value) {
  return normalizeSearchText(value).replace(/[^\p{L}\p{N}]/gu, "");
}

function searchBigrams(value) {
  const normalized = searchableText(value);
  if (normalized.length < 2) return normalized ? [normalized] : [];
  const grams = [];
  for (let i = 0; i < normalized.length - 1; i += 1) grams.push(normalized.slice(i, i + 2));
  return grams;
}

function parseSearchTerms(query) {
  return String(query || "")
    .split(/\s+/)
    .map((raw) => raw.trim())
    .filter(Boolean)
    .map((raw) => ({ raw, normalized: searchableText(raw), bigrams: [...new Set(searchBigrams(raw))] }))
    .filter((term) => term.normalized.length > 0);
}

function normalizeWithMap(text) {
  const original = String(text || "");
  let normalized = "";
  const map = [];
  for (let index = 0; index < original.length; index += 1) {
    const folded = original[index].normalize("NFKC").toLowerCase();
    for (const char of folded) {
      if (/[\p{L}\p{N}]/u.test(char)) {
        normalized += char;
        map.push(index);
      }
    }
  }
  return { original, normalized, map };
}

const DIGIT_RE = /[0-9]/;

// "600万円" must not match inside "3,600万円" (issue #62). The compact search
// text drops punctuation, so the digit chain has to be judged on the original
// characters, allowing one thousands separator to stay inside the number.
function gluedToNumberLeft(original, startIndex) {
  let index = startIndex - 1;
  let separators = 0;
  while (index >= 0 && separators <= 1) {
    const folded = original[index].normalize("NFKC");
    if (folded === "," || folded === ".") {
      separators += 1;
      index -= 1;
      continue;
    }
    return DIGIT_RE.test(folded);
  }
  return false;
}

function gluedToNumberRight(original, endIndex) {
  let index = endIndex;
  let separators = 0;
  while (index < original.length && separators <= 1) {
    const folded = original[index].normalize("NFKC");
    if (folded === "," || folded === ".") {
      separators += 1;
      index += 1;
      continue;
    }
    return DIGIT_RE.test(folded);
  }
  return false;
}

function numericBoundaryOk(original, startOrig, endOrig, termNormalized) {
  if (!original) return true;
  if (DIGIT_RE.test(termNormalized[0] || "") && gluedToNumberLeft(original, startOrig)) return false;
  if (DIGIT_RE.test(termNormalized[termNormalized.length - 1] || "") && gluedToNumberRight(original, endOrig)) return false;
  return true;
}

function phraseMatchIn(haystack, termNormalized) {
  if (!haystack || !termNormalized) return { found: false, start: -1, end: -1, boundaryRejected: false };
  const compact = haystack.normalized;
  let from = 0;
  let boundaryRejected = false;
  while (from + termNormalized.length <= compact.length) {
    const start = compact.indexOf(termNormalized, from);
    if (start < 0) break;
    const end = start + termNormalized.length;
    const startOrig = haystack.map[start];
    const endOrig = (haystack.map[end - 1] ?? startOrig) + 1;
    if (numericBoundaryOk(haystack.original, startOrig, endOrig, termNormalized)) {
      return { found: true, start, end, boundaryRejected: false };
    }
    // The characters are there but the term sits inside a larger number
    // (3,600万円 for 600万円), which matters for the exact:false counters.
    boundaryRejected = true;
    from = start + 1;
  }
  return { found: false, start: -1, end: -1, boundaryRejected };
}

function bestWindowStart(originals, size) {
  let best = originals[0];
  let bestDistinct = -1;
  for (const candidate of originals) {
    const from = candidate - 40;
    const to = from + size;
    const distinct = new Set(originals.filter((value) => value >= from && value < to)).size;
    if (distinct > bestDistinct) {
      bestDistinct = distinct;
      best = candidate;
    }
  }
  return Math.max(0, best - 40);
}

function buildSearchWindow(haystack, termMatches, size) {
  const original = haystack && haystack.original ? haystack.original : "";
  const matches = (termMatches || []).filter((match) => match && match.startOrig >= 0);
  if (!original) return { snippet: "", highlights: [] };
  const start = matches.length ? bestWindowStart(matches.map((match) => match.startOrig), size) : 0;
  const end = Math.min(original.length, start + size);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < original.length ? "…" : "";
  const snippet = `${prefix}${original.slice(start, end)}${suffix}`;
  const highlights = matches
    .filter((match) => match.startOrig >= start && match.startOrig < end)
    .map((match) => ({
      term: match.term,
      start: match.startOrig - start + prefix.length,
      end: Math.min(end, Math.max(match.endOrig, match.startOrig + 1)) - start + prefix.length,
      match_type: match.approximate ? "approximate" : "exact",
    }));
  return { snippet, highlights };
}

function invalidParams(message) {
  return new ProtocolError(-32602, message);
}

function canonicalLawId(value) {
  const match = CANONICAL_ID_RE.exec(String(value || "").trim());
  if (!match) return null;
  return `r${match[1]}RG${match[2]}`;
}

function requireCanonicalLawId(value) {
  const canonical = canonicalLawId(value);
  if (!canonical) throw invalidParams("law_id must match ^r\\d+RG\\d+$");
  return canonical;
}

function toPositiveInt(value) {
  const digits = String(value === undefined || value === null ? "" : value).normalize("NFKC").replace(/[^0-9]/g, "");
  if (!digits) return null;
  const number = Number(digits);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function rejectAsof(input) {
  const value = input.asof;
  if (value === undefined || value === null || String(value).trim() === "") return;
  throw invalidParams(
    "asof is not supported. This MCP serves only the currently published version of every ordinance. Read reiki_status for content_current_date and data_version; historical snapshots are not published."
  );
}

function snippetFor(text, grams, limit = SNIPPET_CHARS) {
  const flat = String(text || "").replace(/\s+/g, " ").trim();
  if (flat.length <= limit) return flat;
  let at = -1;
  for (const gram of grams) {
    const index = flat.indexOf(gram);
    if (index >= 0 && (at < 0 || index < at)) at = index;
  }
  const start = Math.max(0, (at < 0 ? 0 : at) - 40);
  return flat.slice(start, start + limit);
}

function countOccurrences(haystack, needle) {
  if (!needle) return 0;
  let count = 0;
  let index = haystack.indexOf(needle);
  while (index >= 0) {
    count += 1;
    index = haystack.indexOf(needle, index + needle.length);
  }
  return count;
}

function scoreUnit(text, grams) {
  const haystack = normalizeSearchText(text);
  let matched = 0;
  let hits = 0;
  for (const gram of grams) {
    const found = countOccurrences(haystack, gram);
    if (found > 0) {
      matched += 1;
      hits += found;
    }
  }
  if (!matched) return 0;
  const coverage = matched / grams.length;
  return Math.round((coverage * 100 + Math.min(hits, 30)) * 100) / 100;
}

function paragraphText(paragraph) {
  const parts = [String(paragraph.text || "")];
  for (const item of paragraph.items || []) {
    if (item && typeof item === "object") parts.push(String(item.text || ""));
  }
  return parts.join(" ").replace(/\s+/g, " ").trim();
}

function articleText(article) {
  const text = String(article.text || "").replace(/\s+/g, " ").trim();
  if (text) return text;
  const paragraphs = Array.isArray(article.paragraphs) ? article.paragraphs : [];
  return paragraphs.map((paragraph) => paragraphText(paragraph)).join(" ").replace(/\s+/g, " ").trim();
}

function lawUnits(law) {
  const units = [];
  const bodyText = String(law.body_text || "").replace(/\s+/g, " ").trim();
  const preamble = bodyText || (Array.isArray(law.preamble) ? law.preamble.join(" ").replace(/\s+/g, " ").trim() : "");
  if (preamble) units.push({ kind: "preamble", label: "前文", heading: "", unitIndex: null, text: preamble });
  for (const article of Array.isArray(law.articles) ? law.articles : []) {
    units.push({
      kind: "article",
      label: String(article.label || ""),
      heading: String(article.heading || ""),
      unitIndex: null,
      text: articleText(article),
    });
  }
  const supplements = Array.isArray(law.supplements) ? law.supplements : [];
  supplements.forEach((supplement, position) => {
    units.push({
      kind: "supplement",
      label: supplements.length > 1 ? `附則${position + 1}` : "附則",
      heading: "",
      unitIndex: position + 1,
      text: String(supplement || ""),
    });
  });
  const tables = Array.isArray(law.appendix_tables) ? law.appendix_tables : [];
  tables.forEach((table, position) => {
    const text = String(table || "");
    const firstLine = text.split("\n")[0].trim();
    const resource = appendixResource(law, position);
    units.push({
      kind: "appendix_table",
      label: (firstLine || `別表${position + 1}`).slice(0, 40),
      heading: "",
      unitIndex: position + 1,
      text,
      content_status: !text.includes("\n") && resource ? "external_resource_only" : "complete",
      resource,
    });
  });
  return units;
}

function appendixResource(law, position) {
  const resources = Array.isArray(law.resources) ? law.resources : [];
  const mapping = Array.isArray(law.appendix_table_resource_index) ? law.appendix_table_resource_index : null;
  if (mapping) {
    const index = mapping[position];
    if (Number.isInteger(index) && index >= 0 && index < resources.length) {
      return resources[index] || null;
    }
    return null;
  }
  return resources[position] || null;
}

function unitId(lawId, unit) {
  if (unit.unitIndex) return `${lawId}#${unit.kind}-${unit.unitIndex}`;
  return `${lawId}#${unit.kind}-${unit.label}`;
}

async function loadSearchManifest(env) {
  return fetchPagesJson(env, "/api/search/manifest.json", { allowNotFound: true });
}

async function callTool(env, name, args) {
  const input = args && typeof args === "object" && !Array.isArray(args) ? args : {};
  if (name === "reiki_status") {
    const [meta, health] = await Promise.all([
      fetchPagesJson(env, "/api/meta.json"),
      fetchPagesJson(env, "/api/health.json"),
    ]);
    const manifest = await fetchPagesJson(env, "/api/search/manifest.json", { allowNotFound: true }).catch(() => null);
    const search = manifest
      ? {
          published: true,
          data_version: manifest.data_version,
          kind: manifest.kind,
          law_count: manifest.law_count,
          chunk_count: manifest.chunk_count,
          chunk_shards: Array.isArray(manifest.files?.chunks) ? manifest.files.chunks.length : null,
          posting_shards: Array.isArray(manifest.files?.postings) ? manifest.files.postings.length : null,
        }
      : { published: false };
    return textResult(JSON.stringify({ meta, health, search }, null, 2));
  }
  if (name === "search_laws_by_title") {
    const query = String(input.query || "").trim();
    if (!query) throw invalidParams("query is required");
    const limit = Math.min(Math.max(Number(input.limit) || 10, 1), 50);
    const index = await fetchPagesJson(env, "/api/search/title-index.json", { allowNotFound: true });
    if (!index) throw new ToolExecutionError("Pages fetch failed: 404 title index /api/search/title-index.json. The published API has no title index yet; run the Pages workflow with full_build=true.");
    const laws = Array.isArray(index.laws) ? index.laws : [];
    const matched = laws
      .map((law) => ({ law, score: scoreLaw(law, query) }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || String(a.law.id).localeCompare(String(b.law.id)))
      .slice(0, limit)
      .map((item) => ({
        id: item.law.id,
        title: item.law.title,
        ordinance_number: item.law.ordinance_number || "",
        classification: item.law.classification || "",
        enacted_date: item.law.enacted_date || "",
        article_count: item.law.article_count === undefined ? null : item.law.article_count,
        source_url: item.law.source_url || "",
      }));
    return textResult(
      JSON.stringify({ query, data_version: index.data_version || "", count: matched.length, laws: matched }, null, 2)
    );
  }
  if (name === "get_law") {
    rejectAsof(input);
    const lawId = requireCanonicalLawId(input.law_id);
    const law = await fetchPagesJson(env, `/api/laws/${lawId}.json`, { allowNotFound: true });
    if (!law) {
      return textResult(
        JSON.stringify({ law_id: lawId, found: false, reason: "not_found", message: "The published API has no law with this law_id." }, null, 2)
      );
    }
    return textResult(JSON.stringify(law, null, 2));
  }
  if (name === "get_article") {
    rejectAsof(input);
    const lawId = requireCanonicalLawId(input.law_id);
    const label = String(input.article_label || "").trim();
    if (!label) throw invalidParams("article_label is required");
    if (input.item !== undefined && input.item !== null && String(input.item).trim() !== "" && (input.paragraph === undefined || input.paragraph === null || String(input.paragraph).trim() === "")) {
      throw invalidParams("paragraph is required when item is given");
    }
    const law = await fetchPagesJson(env, `/api/laws/${lawId}.json`, { allowNotFound: true });
    if (!law) {
      return textResult(
        JSON.stringify({ law_id: lawId, found: false, reason: "not_found", message: "The published API has no law with this law_id." }, null, 2)
      );
    }
    const articles = Array.isArray(law.articles) ? law.articles : [];
    const found = articles.filter((article) => article.label === label);
    if (!found.length) {
      const available = articles.map((article) => article.label).join(", ");
      return textResult(JSON.stringify({ law_id: lawId, article_label: label, found: false, available_labels: available }, null, 2));
    }
    const article = found[0];
    const paragraphWanted = toPositiveInt(input.paragraph);
    const itemWanted = toPositiveInt(input.item);
    if (paragraphWanted === null) {
      return textResult(
        JSON.stringify(
          {
            law_id: lawId,
            title: law.title,
            data_version: law.data_version || "",
            content_current_date: law.content_current_date || "",
            article_label: label,
            heading: article.heading || "",
            found: true,
            articles: found,
          },
          null,
          2
        )
      );
    }
    const paragraphs = Array.isArray(article.paragraphs) ? article.paragraphs : [];
    const paragraph = paragraphs.find((entry) => Number(entry.number) === paragraphWanted);
    if (!paragraph) {
      return textResult(
        JSON.stringify(
          {
            law_id: lawId,
            title: law.title,
            article_label: label,
            found: false,
            available_paragraphs: paragraphs.map((entry) => Number(entry.number)),
          },
          null,
          2
        )
      );
    }
    const items = Array.isArray(paragraph.items) ? paragraph.items : [];
    if (itemWanted !== null) {
      const item = items.find((entry) => toPositiveInt(entry.label) === itemWanted);
      if (!item) {
        return textResult(
          JSON.stringify(
            {
              law_id: lawId,
              title: law.title,
              article_label: label,
              paragraph: paragraphWanted,
              found: false,
              available_items: items.map((entry) => String(entry.label)),
            },
            null,
            2
          )
        );
      }
      return textResult(
        JSON.stringify(
          {
            law_id: lawId,
            title: law.title,
            data_version: law.data_version || "",
            content_current_date: law.content_current_date || "",
            article_label: label,
            heading: article.heading || "",
            found: true,
            paragraph: { number: paragraphWanted, text: paragraph.text, items: [item] },
          },
          null,
          2
        )
      );
    }
    return textResult(
      JSON.stringify(
        {
          law_id: lawId,
          title: law.title,
          data_version: law.data_version || "",
          content_current_date: law.content_current_date || "",
          article_label: label,
          heading: article.heading || "",
          found: true,
          paragraph: { number: paragraphWanted, text: paragraph.text, items },
        },
        null,
        2
      )
    );
  }
  if (name === "get_toc") {
    rejectAsof(input);
    const lawId = requireCanonicalLawId(input.law_id);
    const law = await fetchPagesJson(env, `/api/laws/${lawId}.json`, { allowNotFound: true });
    if (!law) {
      return textResult(
        JSON.stringify({ law_id: lawId, found: false, reason: "not_found", message: "The published API has no law with this law_id." }, null, 2)
      );
    }
    const articles = Array.isArray(law.articles) ? law.articles : [];
    const supplements = Array.isArray(law.supplements) ? law.supplements : [];
    const tables = Array.isArray(law.appendix_tables) ? law.appendix_tables : [];
    const chapters = Array.isArray(law.chapters) ? law.chapters : [];
    const resources = Array.isArray(law.resources) ? law.resources : [];
    const offset = Math.max(Number(input.offset) || 0, 0);
    const limit = Math.min(Math.max(Number(input.limit) || 60, 1), 200);
    const page = articles.slice(offset, offset + limit);
    const nextOffset = offset + page.length < articles.length ? offset + page.length : null;
    return textResult(
      JSON.stringify(
        {
          law_id: lawId,
          title: law.title,
          data_version: law.data_version || "",
          content_current_date: law.content_current_date || "",
          article_count: articles.length,
          supplement_count: supplements.length,
          appendix_table_count: tables.length,
          offset,
          limit,
          next_offset: nextOffset,
          chapters: chapters.map((chapter) => ({
            kind: chapter.kind || "chapter",
            number: chapter.number || "",
            title: chapter.title || "",
            text: chapter.text || "",
          })),
          resources: resources.map((resource) =>
            resource
              ? { label: resource.label || "", href: resource.href || "", image_url: resource.image_url || "" }
              : null
          ),
          articles: page.map((article) => ({
            label: article.label,
            heading: article.heading || "",
            chapter: article.chapter || "",
            chapter_title: article.chapter_title || "",
            section: article.section || "",
            section_title: article.section_title || "",
          })),
          supplements: supplements.map((_, position) => (supplements.length > 1 ? `附則${position + 1}` : "附則")),
          appendix_tables: tables.map((table, position) => {
            const firstLine = String(table || "").split("\n")[0].trim();
            return (firstLine || `別表${position + 1}`).slice(0, 40);
          }),
        },
        null,
        2
      )
    );
  }
  if (name === "get_unit") {
    rejectAsof(input);
    const lawId = requireCanonicalLawId(input.law_id);
    const rawKind = String(input.kind || "").trim();
    const kindAliases = {
      appendix_table: "appendix_table",
      beppyo: "appendix_table",
      table: "appendix_table",
      supplement: "supplement",
      suppl: "supplement",
    };
    const kind = kindAliases[rawKind];
    if (!kind) throw invalidParams("kind must be appendix_table (or beppyo) or supplement (or suppl)");
    const n = toPositiveInt(input.n);
    if (n === null) throw invalidParams("n must be a 1-based unit number");
    const law = await fetchPagesJson(env, `/api/laws/${lawId}.json`, { allowNotFound: true });
    if (!law) {
      return textResult(
        JSON.stringify({ law_id: lawId, found: false, reason: "not_found", message: "The published API has no law with this law_id." }, null, 2)
      );
    }
    const units = kind === "appendix_table" ? (Array.isArray(law.appendix_tables) ? law.appendix_tables : []) : Array.isArray(law.supplements) ? law.supplements : [];
    if (n > units.length) {
      return textResult(
        JSON.stringify({ law_id: lawId, title: law.title, kind, n, found: false, available_n: units.map((_, position) => position + 1) }, null, 2)
      );
    }
    const text = String(units[n - 1] || "");
    const label = kind === "appendix_table" ? (text.split("\n")[0].trim() || `別表${n}`).slice(0, 40) : units.length > 1 ? `附則${n}` : "附則";
    const unitResource = kind === "appendix_table" ? appendixResource(law, n - 1) : null;
    const contentStatus = kind === "appendix_table" && unitResource && !text.includes("\n") ? "external_resource_only" : "complete";
    return textResult(
      JSON.stringify(
        {
          law_id: lawId,
          title: law.title,
          data_version: law.data_version || "",
          content_current_date: law.content_current_date || "",
          kind,
          n,
          unit_id: `${lawId}#${kind}-${n}`,
          label,
          found: true,
          text,
          content_status: contentStatus,
          resource: unitResource
            ? { label: unitResource.label || "", href: unitResource.href || "", image_url: unitResource.image_url || "" }
            : null,
          source_url: law.source_url || "",
        },
        null,
        2
      )
    );
  }
  if (name === "search_laws_by_content") {
    const query = String(input.query || "").trim();
    if (!query) throw invalidParams("query is required");
    if (searchableText(query).length < MIN_QUERY_CHARS) {
      throw invalidParams(
        `query must contain at least ${MIN_QUERY_CHARS} searchable characters after normalization, because the body index stores bigrams only. Use a longer phrase such as 税金 instead of 税.`
      );
    }
    const terms = parseSearchTerms(query);
    if (!terms.length) throw invalidParams("query must contain searchable characters");
    const limit = Math.min(Math.max(Number(input.limit) || 10, 1), 50);
    const operator = String(input.operator || "AND").toUpperCase() === "OR" ? "OR" : "AND";
    const rawScope = String(input.scope || "chunk").toLowerCase();
    const scope = rawScope === "law" ? "law" : "chunk";
    const groupBy = scope === "law" ? "law" : String(input.group_by || "chunk").toLowerCase() === "law" ? "law" : "chunk";
    const exact = input.exact === undefined ? true : input.exact !== false && String(input.exact) !== "false";
    const snippetWindow = Math.min(Math.max(Number(input.snippet_chars) || SNIPPET_WINDOW, MIN_SNIPPET_CHARS), MAX_SNIPPET_CHARS);
    const scopedLawId =
      input.law_id === undefined || input.law_id === null || String(input.law_id).trim() === ""
        ? ""
        : requireCanonicalLawId(input.law_id);

    if (scopedLawId) {
      const law = await fetchPagesJson(env, `/api/laws/${scopedLawId}.json`, { allowNotFound: true });
      if (!law) {
        return textResult(
          JSON.stringify(
            {
              query,
              law_id: scopedLawId,
              found: false,
              reason: "not_found",
              count: 0,
              pages_fetches: 1,
              completeness: "complete",
              truncated: false,
              truncation_reasons: [],
              results: [],
            },
            null,
            2
          )
        );
      }
      const units = lawUnits(law);
      const examined = units.map((unit) => {
        const haystack = normalizeWithMap(`${unit.label} ${unit.heading} ${unit.text}`);
        const matches = terms.map((term) => {
          const phrase = phraseMatchIn(haystack, term.normalized);
          if (phrase.found) return { term: term.raw, found: true, approximate: false, start: phrase.start, end: phrase.end };
          if (exact) {
            return {
              term: term.raw,
              found: false,
              approximate: false,
              start: -1,
              end: -1,
              boundaryRejected: Boolean(phrase.boundaryRejected),
            };
          }
          const loose = haystack.normalized.indexOf(term.normalized);
          if (loose >= 0) return { term: term.raw, found: true, approximate: true, start: loose, end: loose + term.normalized.length };
          const gramsOk = term.bigrams.length > 0 && term.bigrams.every((gram) => haystack.normalized.includes(gram));
          return { term: term.raw, found: gramsOk, approximate: true, start: -1, end: -1 };
        });
        return { unit, haystack, matches, matched: matches.filter((entry) => entry.found) };
      });
      const windowMatch = (entry, match) => ({
        term: match.term,
        startOrig: entry.haystack.map[match.start] ?? -1,
        endOrig: match.start >= 0 ? (entry.haystack.map[match.end - 1] ?? match.start) + 1 : -1,
        approximate: Boolean(match.approximate),
      });
      let filteredOutExact = 0;
      let filteredOutNoTerm = 0;
      let truncated = false;
      let results = [];
      if (scope === "law") {
        const evidence = new Map();
        for (const entry of examined) {
          for (const match of entry.matched) {
            if (evidence.has(match.term)) continue;
            const window = buildSearchWindow(entry.haystack, [windowMatch(entry, match)], snippetWindow);
            evidence.set(match.term, {
              term: match.term,
              label: entry.unit.label,
              heading: entry.unit.heading || "",
              kind: entry.unit.kind,
              unit_id: unitId(law.id, entry.unit),
              snippet: window.snippet,
              highlights: window.highlights,
              match_type: match.approximate ? "approximate" : "exact",
              content_status: entry.unit.content_status || "complete",
            });
          }
        }
        const evidenceList = [...evidence.values()];
        const first = evidenceList[0] || null;
        const satisfied = operator === "AND" ? terms.every((term) => evidence.has(term.raw)) : evidence.size > 0;
        if (satisfied && first) {
          results = [
            {
              law_id: law.id,
              title: law.title,
              label: first.label,
              heading: first.heading,
              kind: first.kind,
              unit_id: first.unit_id,
              source_url: law.source_url || "",
              score: 1,
              snippet: first.snippet,
              highlights: first.highlights,
              match_type: evidenceList.every((item) => item.match_type === "exact") ? "exact" : "approximate",
              content_status: first.content_status || "complete",
              resource: first.resource || null,
              matched_terms: evidenceList.map((item) => item.term),
              unmatched_terms: terms.map((term) => term.raw).filter((raw) => !evidence.has(raw)),
              matches: evidenceList,
            },
          ];
        }
        truncated = results.length > limit;
      } else {
        const qualifies = examined.filter((entry) => (operator === "AND" ? entry.matched.length === terms.length : entry.matched.length > 0));
        for (const entry of examined) {
          if (qualifies.includes(entry)) continue;
          if (entry.matched.length > 0 && exact) filteredOutExact += 1;
          // A term whose characters exist but sit inside a larger number was
          // rejected by the exact rule, not a term the law never mentions.
          else if (exact && entry.matches.some((match) => match.boundaryRejected)) filteredOutExact += 1;
          else filteredOutNoTerm += 1;
        }
        const scored = qualifies
          .map((entry) => ({ entry, score: scoreUnit(entry.unit.text, terms.flatMap((term) => term.bigrams)) }))
          .sort((a, b) => b.score - a.score || a.entry.unit.label.localeCompare(b.entry.unit.label));
        truncated = scored.length > limit;
        results = scored.slice(0, limit).map(({ entry, score }) => {
          const window = buildSearchWindow(entry.haystack, entry.matched.map((match) => windowMatch(entry, match)), snippetWindow);
          return {
            law_id: law.id,
            title: law.title,
            label: entry.unit.label,
            heading: entry.unit.heading || "",
            kind: entry.unit.kind,
            unit_index: entry.unit.unitIndex,
            unit_id: unitId(law.id, entry.unit),
            snippet: window.snippet,
            highlights: window.highlights,
            source_url: law.source_url || "",
            score,
            match_type: entry.matched.every((match) => !match.approximate) ? "exact" : "approximate",
            content_status: entry.unit.content_status || "complete",
            resource: entry.unit.resource || null,
            matched_terms: entry.matched.map((match) => match.term),
            unmatched_terms: terms.map((term) => term.raw).filter((raw) => !entry.matched.some((match) => match.term === raw)),
          };
        });
      }
      return textResult(
        JSON.stringify(
          {
            query,
            law_id: scopedLawId,
            operator,
            scope,
            group_by: groupBy,
            exact,
            data_version: law.data_version || "",
            content_current_date: law.content_current_date || "",
            count: results.length,
            limit,
            pages_fetches: 1,
            candidates: examined.length,
            candidates_examined: examined.length,
            filtered_out_exact: filteredOutExact,
            filtered_out_no_term: filteredOutNoTerm,
            completeness: truncated ? "partial" : "complete",
            truncated,
            truncation_reasons: truncated ? ["result_limit"] : [],
            results,
          },
          null,
          2
        )
      );
    }

    const budget = { used: 0 };
    const reasons = new Set();
    const manifest = await loadSearchManifest(env);
    budget.used += 1;
    if (!manifest) {
      throw new ToolExecutionError(
        "本文検索インデックス未公開: /api/search/manifest.json returned 404. Run the Pages workflow with full_build=true so the bigram TF-IDF index is published before the Worker serves search_laws_by_content."
      );
    }
    const dataVersion = String(manifest.data_version || "");
    const chunkShardSize = Number(manifest.chunk_shard_size) || CHUNK_SHARD_SIZE;
    const countedFetch = async (path, cacheBust) => {
      if (budget.used >= MAX_PAGES_FETCHES) {
        reasons.add("pages_fetch_budget");
        return null;
      }
      budget.used += 1;
      return fetchPagesJson(env, path, { cacheBust });
    };
    const loadVersioned = async (path) => {
      const data = await countedFetch(path);
      if (!data) return null;
      if (!dataVersion || data.data_version === undefined || data.data_version === dataVersion) return data;
      const retried = await countedFetch(path, dataVersion);
      if (retried && retried.data_version === dataVersion) return retried;
      throw new ToolExecutionError(
        `search index version mismatch: ${path} reports data_version=${data && data.data_version}, manifest expects ${dataVersion}. Re-run the Pages workflow with full_build=true so every posting and chunk shard is republished, then retry.`
      );
    };

    const gramShards = new Map();
    for (const term of terms) {
      for (const gram of term.bigrams) {
        if (!gramShards.has(gram)) gramShards.set(gram, fnv1a32(gram) % POSTING_SHARD_COUNT);
      }
    }
    const shardGramCount = new Map();
    for (const shard of gramShards.values()) shardGramCount.set(shard, (shardGramCount.get(shard) || 0) + 1);
    const allShardIds = [...shardGramCount.keys()].sort(
      (a, b) => shardGramCount.get(b) - shardGramCount.get(a) || a - b
    );
    const shardIds = allShardIds.slice(0, MAX_POSTING_SHARDS).sort((a, b) => a - b);
    const scores = new Map();
    const gramChunks = new Map();
    for (const shard of shardIds) {
      if (budget.used >= MAX_PAGES_FETCHES) {
        reasons.add("pages_fetch_budget");
        break;
      }
      const data = await loadVersioned(`/api/search/postings-${String(shard).padStart(2, "0")}.json`);
      if (!data) break;
      const postings = data && typeof data === "object" ? data.terms || {} : {};
      for (const [gram, shardId] of gramShards) {
        if (shardId !== shard) continue;
        const entries = Array.isArray(postings[gram]) ? postings[gram] : [];
        const chunks = new Set();
        for (const entry of entries) {
          if (!Array.isArray(entry) || entry.length < 2) continue;
          const [index, score] = entry;
          scores.set(index, (scores.get(index) || 0) + Number(score || 0));
          chunks.add(index);
        }
        gramChunks.set(gram, chunks);
      }
    }
    const gramComplete = (index) =>
      terms.every(
        (term) => term.bigrams.length > 0 && term.bigrams.every((gram) => (gramChunks.get(gram) || new Set()).has(index))
      );
    const ranked = [...scores.entries()]
      .sort((a, b) => b[1] - a[1] || a[0] - b[0])
      .map(([index]) => index);
    // Candidates holding every bigram of every term are cheap to verify and far
    // more likely to satisfy AND, so they are walked before coincidental hits.
    const rankedIndexes = [...ranked.filter(gramComplete), ...ranked.filter((index) => !gramComplete(index))];
    const byShard = new Map();
    for (const index of rankedIndexes) {
      const shard = Math.floor(index / chunkShardSize);
      if (!byShard.has(shard)) byShard.set(shard, []);
      byShard.get(shard).push(index);
    }
    // A fetch costs one subrequest whatever it returns, so shards holding the
    // most candidates are read first and the budget buys more examined chunks.
    const shardOrder = [...byShard.entries()].sort((a, b) => b[1].length - a[1].length || a[0] - b[0]).map(([shard]) => shard);
    const chunkCache = new Map();
    const results = [];
    const lawGroups = new Map();
    const perLaw = new Map();
    const done = new Set();
    let walked = 0;
    let filteredOutExact = 0;
    let filteredOutNoTerm = 0;
    let skippedPerLaw = 0;

    const loadChunkShard = async (shard) => {
      if (chunkCache.has(shard)) return chunkCache.get(shard);
      const data = await loadVersioned(`/api/search/chunks-${String(shard).padStart(3, "0")}.json`);
      if (!data) return null;
      const byIndex = new Map();
      for (const row of Array.isArray(data.chunks) ? data.chunks : []) byIndex.set(row.i, row);
      chunkCache.set(shard, byIndex);
      return byIndex;
    };

    const dropCandidate = (rejectedByExact) => {
      if (rejectedByExact) filteredOutExact += 1;
      else filteredOutNoTerm += 1;
    };

    const evaluateChunk = (index, row) => {
      const body = String(row.text || row.snippet || "");
      const raw = `${row.label || ""} ${row.heading || ""} ${body}`;
      const hasText = Boolean(row.text);
      const rejectedByExact = exact && hasText;
      // Cheap first pass: native string work only, so candidates that cannot
      // hold a term are dropped before the per-character mapping loop runs.
      // That is what keeps wide AND queries inside the Worker CPU budget
      // (issue #67) instead of returning HTTP 503.
      const flat = searchableText(raw);
      const candidates = [];
      for (const term of terms) {
        if (hasText && flat.indexOf(term.normalized) >= 0) {
          candidates.push(term);
          continue;
        }
        const gramsOk = term.bigrams.length > 0 && term.bigrams.every((gram) => flat.includes(gram));
        if ((!exact || !hasText) && gramsOk) {
          candidates.push(term);
          continue;
        }
        if (operator === "AND" && scope === "chunk") {
          dropCandidate(rejectedByExact);
          return;
        }
      }
      if (!candidates.length) {
        dropCandidate(rejectedByExact);
        return;
      }

      const haystack = normalizeWithMap(raw);
      const verified = candidates.map((term) => {
        // Phrase verification runs first even when exact=false, so a chunk that
        // really contains the phrase keeps match_type=exact instead of being
        // reported approximate or dropped (issue #63).
        const phrase = phraseMatchIn(haystack, term.normalized);
        if (phrase.found) return { raw: term.raw, found: true, approximate: false, start: phrase.start, end: phrase.end };
        if (rejectedByExact) return { raw: term.raw, found: false, approximate: false, start: -1, end: -1 };
        // The candidate reached this point because every bigram of the term is
        // present, so exact=false must keep it as an approximate hit even when
        // the phrase never occurs contiguously (the 600点/500万円 shape from
        // issue #52). There is simply no highlight position for it.
        const loose = haystack.normalized.indexOf(term.normalized);
        if (loose < 0) return { raw: term.raw, found: true, approximate: true, start: -1, end: -1 };
        return { raw: term.raw, found: true, approximate: true, start: loose, end: loose + term.normalized.length };
      });
      const matched = verified.filter((entry) => entry.found);
      // A candidate can hold every bigram without the phrase, which is exactly
      // the 600点/500万円 trap in issue #52.
      if (!matched.length) {
        dropCandidate(rejectedByExact);
        return;
      }
      if (scope === "chunk" && operator === "AND" && matched.length !== terms.length) {
        dropCandidate(rejectedByExact);
        return;
      }
      const score = Math.round((scores.get(index) || 0) * 10000) / 10000;
      const termMatches = matched.map((entry) => ({
        term: entry.raw,
        startOrig: entry.start >= 0 ? haystack.map[entry.start] ?? -1 : -1,
        endOrig: entry.start >= 0 ? (haystack.map[entry.end - 1] ?? entry.start) + 1 : -1,
        approximate: Boolean(entry.approximate),
      }));
      const resultMatchType = matched.every((entry) => !entry.approximate) ? "exact" : "approximate";

      if (scope === "law" || groupBy === "law") {
        const lawId = row.law_id;
        if (!lawGroups.has(lawId)) {
          lawGroups.set(lawId, { law_id: lawId, title: row.title, score, matches: new Map() });
        }
        const group = lawGroups.get(lawId);
        group.score = Math.max(group.score, score);
        for (const entry of matched) {
          if (group.matches.has(entry.raw)) continue;
          const window = buildSearchWindow(
            haystack,
            termMatches.filter((match) => match.term === entry.raw),
            snippetWindow
          );
          group.matches.set(entry.raw, {
            term: entry.raw,
            label: row.label,
            heading: row.heading || "",
            kind: row.kind || "",
            unit_id: unitId(lawId, { label: row.label, kind: row.kind, unitIndex: row.unit_index }),
            snippet: window.snippet,
            highlights: window.highlights,
            match_type: entry.approximate ? "approximate" : "exact",
            content_status: row.content_status || "complete",
          });
        }
        const satisfied =
          operator === "AND" ? terms.every((term) => group.matches.has(term.raw)) : group.matches.size > 0;
        if (satisfied && !results.some((item) => item.law_id === lawId)) {
          const window = buildSearchWindow(haystack, termMatches.slice(0, 1), snippetWindow);
          const groupMatches = [...group.matches.values()];
          results.push({
            law_id: lawId,
            title: row.title,
            label: row.label,
            heading: row.heading || "",
            kind: row.kind || "",
            source_url: row.source_url || "",
            score: group.score,
            snippet: window.snippet,
            highlights: window.highlights,
            match_type: groupMatches.every((item) => item.match_type === "exact") ? "exact" : "approximate",
            content_status: row.content_status || "complete",
            resource: row.resource || null,
            matched_terms: [...group.matches.keys()],
            unmatched_terms: terms.map((term) => term.raw).filter((raw) => !group.matches.has(raw)),
            matches: groupMatches,
          });
        }
        return;
      }

      const count = perLaw.get(row.law_id) || 0;
      if (count >= MAX_RESULTS_PER_LAW) {
        skippedPerLaw += 1;
        return;
      }
      perLaw.set(row.law_id, count + 1);
      const window = buildSearchWindow(haystack, termMatches, snippetWindow);
      results.push({
        law_id: row.law_id,
        title: row.title,
        label: row.label,
        heading: row.heading || "",
        kind: row.kind || "",
        source_url: row.source_url || "",
        score,
        snippet: window.snippet,
        highlights: window.highlights,
        match_type: resultMatchType,
        content_status: row.content_status || "complete",
        resource: row.resource || null,
        matched_terms: matched.map((entry) => entry.raw),
        unmatched_terms: terms.map((term) => term.raw).filter((raw) => !matched.some((entry) => entry.raw === raw)),
      });
    };

    const collectTarget = Math.min(limit * 3, 60);
    // With exact:false, approximate hits must not crowd out the exact hits that
    // later shards still hold. Keep walking until enough *exact* results are
    // collected, but cap the approximate filler so a query with no exact hit at
    // all does not spend the whole fetch budget (issues #79, #78).
    const approximateFillerCap = collectTarget * 4;
    const collectedEnough = () => {
      if (results.length < collectTarget) return false;
      if (exact) return true;
      const exactCount = results.filter((row) => row.match_type === "exact").length;
      return exactCount >= collectTarget || results.length >= approximateFillerCap;
    };
    for (const shard of shardOrder) {
      if (collectedEnough()) break;
      if (walked >= MAX_CANDIDATES_WALKED) {
        reasons.add("candidate_scan_limit");
        break;
      }
      const shardRows = await loadChunkShard(shard);
      if (!shardRows) {
        reasons.add("pages_fetch_budget");
        break;
      }
      // One shard holds up to 500 chunks, so evaluating every candidate in it
      // keeps the fetch budget for coverage instead of repeat downloads.
      for (const mate of byShard.get(shard) || []) {
        if (done.has(mate)) continue;
        if (collectedEnough()) break;
        if (walked >= MAX_CANDIDATES_WALKED) {
          reasons.add("candidate_scan_limit");
          break;
        }
        const row = shardRows.get(mate);
        done.add(mate);
        if (!row) continue;
        walked += 1;
        evaluateChunk(mate, row);
      }
      // Each shard is visited once, so holding it after the walk only keeps up
      // to 500 full chunk texts alive for nothing (issue #67).
      chunkCache.delete(shard);
    }
    if (skippedPerLaw > 0 && results.length < limit) reasons.add("max_results_per_law");
    // Exact evidence outranks approximate evidence regardless of score: an
    // appendix boosted approximate hit must not sit above the article that
    // actually contains the phrase (issue #79).
    results.sort(
      (a, b) =>
        (a.match_type === "exact" ? 0 : 1) - (b.match_type === "exact" ? 0 : 1) ||
        b.score - a.score ||
        String(a.law_id).localeCompare(String(b.law_id))
    );
    if (results.length > limit) {
      results.length = limit;
      reasons.add("result_limit");
    }
    const truncationReasons = [...reasons];
    // Only fetch/scan caps mean "some evidence was never examined"; the display
    // limit and the per-law cap mean "more matches exist than shown".
    const coverageReasons = truncationReasons.filter(
      (reason) => reason === "pages_fetch_budget" || reason === "candidate_scan_limit"
    );
    const indexCaps = {
      posting_terms: manifest.posting_terms ?? null,
      posting_entries: manifest.posting_entries ?? null,
      max_postings_per_term: manifest.max_postings_per_term ?? null,
      max_postings_per_law_per_term: manifest.max_postings_per_law_per_term ?? null,
      pages_fetch_limit: MAX_PAGES_FETCHES,
      candidate_scan_limit: MAX_CANDIDATES_WALKED,
      posting_shard_limit: MAX_POSTING_SHARDS,
      snippet_window_chars: snippetWindow,
    };
    return textResult(
      JSON.stringify(
        {
          query,
          terms: terms.map((term) => term.raw),
          operator,
          scope,
          group_by: groupBy,
          exact,
          data_version: dataVersion,
          count: results.length,
          limit,
          pages_fetches: budget.used,
          candidates: rankedIndexes.length,
          candidates_examined: walked,
          filtered_out_no_term: filteredOutNoTerm,
          filtered_out_exact: filteredOutExact,
          skipped_per_law: skippedPerLaw,
          completeness: coverageReasons.length > 0 ? "partial" : "complete",
          truncated: truncationReasons.length > 0,
          truncation_reasons: truncationReasons,
          index_caps: indexCaps,
          results,
        },
        null,
        2
      )
    );
  }
  throw invalidParams(`Unknown tool: ${name}`);
}

const TOOLS = [
  {
    name: "reiki_status",
    description:
      "Return the published static API meta and health (generation time, site current date, data version, law count, failure count) and whether the body-search index is published.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "search_laws_by_title",
    description:
      "Search Higashimatsushima ordinances by title keyword, ordinance number, law ID, or classification fragment. Reads the lightweight title index and returns summaries only (id, title, ordinance number, classification, article count, source_url); use get_law for the body.",
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
    name: "search_laws_by_content",
    description:
      "Two-stage body search over Higashimatsushima ordinances: bigram TF-IDF postings generate candidates, then each candidate chunk is verified against its full text. exact=true (default) keeps only chunks where every query term appears as a contiguous phrase, and a phrase that starts or ends with a digit must sit on a number boundary, so 600万円 does not match inside 3,600万円. exact=false still reports contiguous matches as match_type=exact and labels bigram-only hits approximate. Returns snippet with highlights, match_type, matched/unmatched terms, and completeness counters. Results are bounded: at most 50 postings per term in the index, 3 chunks per law per term, 46 Pages fetches and 300 examined candidates per call. scope=chunk requires all terms in one chunk; scope=law aggregates per ordinance and returns matches[] with the evidence chunk for each term. law_id restricts the search to one ordinance and reports the scope it actually applied.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Japanese keyword query with at least 2 characters; space-separated terms, e.g. 随意契約 600万円" },
        limit: { type: "number", description: "Maximum results, 1 to 50. Default 10." },
        law_id: { type: "string", description: "Restrict the search to one ordinance, e.g. r122RG00000070" },
        operator: { type: "string", enum: ["AND", "OR"], description: "How multiple terms combine. Default AND." },
        scope: { type: "string", enum: ["chunk", "law"], description: "chunk: all terms in the same chunk. law: all terms somewhere in the same ordinance. Default chunk." },
        group_by: { type: "string", enum: ["chunk", "law"], description: "Collapse results per ordinance. Default chunk (law when scope=law)." },
        exact: { type: "boolean", description: "Verify each term as a contiguous phrase in the chunk text. Default true; false keeps bigram-only matches labelled approximate." },
        snippet_chars: { type: "number", description: "Snippet window size in characters, 80 to 800. Default 280. The window is centred on the match, not on the start of the chunk." },
      },
      required: ["query"],
      additionalProperties: false,
    },
  },
  {
    name: "get_law",
    description:
      "Fetch one ordinance in full: articles, paragraphs, items, supplements, appendix tables and history, by law ID such as r122RG00000002. Only the currently published version is available; asof is rejected.",
    inputSchema: {
      type: "object",
      properties: {
        law_id: { type: "string", description: "Law ID matching ^r\\d+RG\\d+$ (case insensitive)" },
        asof: { type: "string", description: "Unsupported: the service publishes only the current version" },
      },
      required: ["law_id"],
      additionalProperties: false,
    },
  },
  {
    name: "get_article",
    description:
      "Fetch one article of an ordinance by its label such as 第1条 or 第2条の2. Optionally select one paragraph (paragraph=2) and one item (item=2) instead of the whole article. Every response carries data_version and content_current_date so the published version is visible at article level.",
    inputSchema: {
      type: "object",
      properties: {
        law_id: { type: "string", description: "Law ID matching ^r\\d+RG\\d+$" },
        article_label: { type: "string", description: "Article label such as 第1条" },
        paragraph: { type: "number", description: "Optional paragraph number such as 2" },
        item: { type: "number", description: "Optional item number such as 2. Requires paragraph." },
        asof: { type: "string", description: "Unsupported: the service publishes only the current version" },
      },
      required: ["law_id", "article_label"],
      additionalProperties: false,
    },
  },
  {
    name: "get_toc",
    description:
      "Return the table of contents of one ordinance: article labels and headings with offset/limit pagination, plus supplement and appendix table counts and labels. Use it before get_article or get_unit.",
    inputSchema: {
      type: "object",
      properties: {
        law_id: { type: "string", description: "Law ID matching ^r\\d+RG\\d+$" },
        offset: { type: "number", description: "Article offset, default 0" },
        limit: { type: "number", description: "Articles per page, 1 to 200. Default 60." },
        asof: { type: "string", description: "Unsupported: the service publishes only the current version" },
      },
      required: ["law_id"],
      additionalProperties: false,
    },
  },
  {
    name: "get_unit",
    description:
      "Fetch one appendix table or one supplement of an ordinance without loading the whole body: kind=appendix_table (alias beppyo) or supplement (alias suppl), with a 1-based n.",
    inputSchema: {
      type: "object",
      properties: {
        law_id: { type: "string", description: "Law ID matching ^r\\d+RG\\d+$" },
        kind: { type: "string", description: "appendix_table (beppyo) or supplement (suppl)" },
        n: { type: "number", description: "1-based unit number" },
        asof: { type: "string", description: "Unsupported: the service publishes only the current version" },
      },
      required: ["law_id", "kind", "n"],
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
  if (env && env.AUTH_TOKEN) {
    const authorization = request.headers.get("authorization") || "";
    if (!(await bearerOk(authorization, env.AUTH_TOKEN))) {
      return jsonResponse({ jsonrpc: "2.0", id: null, error: { code: -32001, message: "Unauthorized: missing or invalid Bearer token" } }, 401);
    }
  }
  let payload;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error: body must be JSON" } }, 400);
  }
  if (Array.isArray(payload) && payload.length === 0) {
    return jsonResponse({ jsonrpc: "2.0", id: null, error: { code: -32600, message: "Invalid Request: empty batch" } });
  }
  const messages = Array.isArray(payload) ? payload : [payload];
  const responses = [];
  for (const message of messages) {
    if (!message || typeof message !== "object" || Array.isArray(message)) {
      responses.push({ jsonrpc: "2.0", id: null, error: { code: -32600, message: "Invalid Request: expected a JSON-RPC object" } });
      continue;
    }
    const hasValidId = !("id" in message) || message.id === null || typeof message.id === "string" || typeof message.id === "number";
    const responseId = hasValidId && "id" in message ? message.id : null;
    if (!hasValidId) {
      responses.push({ jsonrpc: "2.0", id: null, error: { code: -32600, message: "Invalid Request: id must be a string, number, or null" } });
      continue;
    }
    if (message.jsonrpc !== "2.0" || typeof message.method !== "string" || !message.method) {
      responses.push({ jsonrpc: "2.0", id: responseId, error: { code: -32600, message: "Invalid Request: jsonrpc must be \"2.0\" and method must be a string" } });
      continue;
    }
    if (!("id" in message)) {
      continue;
    }
    const id = message.id;
    const method = message.method;
    try {
      if (method === "initialize") {
        responses.push({
          jsonrpc: "2.0",
          id,
          result: {
            protocolVersion: PROTOCOL_VERSION,
            capabilities: { tools: {} },
            serverInfo: { name: "higashimatsushima-reiki-mcp", version: "0.2.0" },
          },
        });
      } else if (method === "ping") {
        responses.push({ jsonrpc: "2.0", id, result: {} });
      } else if (method === "tools/list") {
        responses.push({ jsonrpc: "2.0", id, result: { tools: TOOLS } });
      } else if (method === "tools/call") {
        const params = message.params;
        if (!params || typeof params !== "object" || Array.isArray(params) || typeof params.name !== "string" || !params.name) {
          throw invalidParams("tools/call params.name is required");
        }
        if (params.arguments !== undefined && (typeof params.arguments !== "object" || params.arguments === null || Array.isArray(params.arguments))) {
          throw invalidParams("tools/call params.arguments must be an object");
        }
        try {
          const result = await callTool(env, params.name, params.arguments || {});
          responses.push({ jsonrpc: "2.0", id, result });
        } catch (error) {
          if (error instanceof ToolExecutionError) {
            responses.push({ jsonrpc: "2.0", id, result: errorTextResult(error.message) });
          } else {
            throw error;
          }
        }
      } else {
        responses.push({ jsonrpc: "2.0", id, error: { code: -32601, message: `Method not found: ${method}` } });
      }
    } catch (error) {
      if (error instanceof ProtocolError) {
        responses.push({ jsonrpc: "2.0", id, error: { code: error.code, message: error.message } });
      } else if (error instanceof ToolExecutionError) {
        responses.push({ jsonrpc: "2.0", id, result: errorTextResult(error.message) });
      } else {
        responses.push({ jsonrpc: "2.0", id, error: { code: -32603, message: error instanceof Error ? error.message : String(error) } });
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
      if (url.pathname === "/live") {
        return jsonResponse({ ok: true, service: "higashimatsushima-reiki-mcp", pages_base: pagesBase(env || {}) });
      }
      if (url.pathname === "/health") {
        let published;
        try {
          published = await fetchPagesJson(env || {}, "/api/health.json");
        } catch (error) {
          published = { error: error instanceof Error ? error.message : String(error) };
          return jsonResponse({ ok: false, service: "higashimatsushima-reiki-mcp", pages_base: pagesBase(env || {}), published }, 503);
        }
        const expected = published && published.expected_count;
        const healthy = Boolean(published) && published.ok === true && published.failure_count === 0 && Number.isInteger(published.law_count) && published.law_count > 0 && Number.isInteger(expected) && expected > 0 && expected === published.law_count;
        return jsonResponse({ ok: healthy, service: "higashimatsushima-reiki-mcp", pages_base: pagesBase(env || {}), published }, healthy ? 200 : 503);
      }
      if (url.pathname === "/mcp") {
        return handleMcp(request, env || {});
      }
      if (url.pathname === "/") {
        return jsonResponse({
          name: "higashimatsushima-reiki-mcp",
          description: "MCP wrapper for the Higashimatsushima City ordinances static API on GitHub Pages. The city site remains the primary source.",
          endpoints: { mcp: "/mcp", health: "/health", live: "/live" },
          tools: TOOLS.map((tool) => tool.name),
          pages_base: pagesBase(env || {}),
        });
      }
      return jsonResponse({ error: "Not found", endpoints: { mcp: "/mcp", health: "/health", live: "/live" } }, 404);
    } catch (error) {
      return jsonResponse({ error: error instanceof Error ? error.message : String(error) }, 500);
    }
  },
};
