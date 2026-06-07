import type { Product, ReviewHit, ReviewSample } from "./types";

export const API_BASE = process.env.HEV_SHOP_API_BASE ?? "";

export function backendEnabled(): boolean {
  return API_BASE.length > 0;
}

const DEFAULT_BACKEND_TIMEOUT_MS = 8_000;
const META_TIMEOUT_MS = 4_000;

type BackendHit = {
  id: string;
  dist: number | null;
  attributes: Record<string, unknown>;
};

export type LayerPerf = {
  // Gateway round-trip in ms (HTTP only — no handler-side work).
  latency_ms: number;
  // `x-layer-cache` header from the gateway. "hit"/"miss"/"miss-on-error"
  // for cache-eligible endpoints (fetch_document, namespace metadata).
  // null for query endpoints — they don't go through the document cache.
  cache_status: string | null;
};

type BackendCountInfo = {
  count: number;
  bounded: boolean;
  timed_out?: boolean;
  shards_saturated?: number;
  shards_total?: number;
  max_distance: number;
  layer_perf?: LayerPerf | null;
};

type BackendSearchResponse = {
  query: string;
  namespace: string;
  hits: BackendHit[];
  stable_as_of?: number | null;
  layer_perf?: LayerPerf | null;
  next_cursor?: string | null;
  count?: BackendCountInfo | null;
};

type BackendRecommendResponse = {
  asin: string;
  namespace: string;
  hits: BackendHit[];
  stable_as_of?: number | null;
  layer_perf?: LayerPerf | null;
  next_cursor?: string | null;
};

export type CountInfo = {
  count: number;
  bounded: boolean;
  max_distance: number;
  layer_perf: LayerPerf | null;
};

type BackendProductResponse = {
  asin: string;
  namespace: string;
  attributes: Record<string, unknown>;
  layer_perf?: LayerPerf | null;
};

export type ProductWithPerf = {
  product: Product;
  layer_perf: LayerPerf | null;
};

export type SearchResult = {
  products: Product[];
  layer_perf: LayerPerf | null;
  stable_as_of: number | null;
  next_cursor: string | null;
  count: CountInfo | null;
};

export type ReviewSearchResult = {
  reviews: ReviewHit[];
  layer_perf: LayerPerf | null;
  stable_as_of: number | null;
  next_cursor: string | null;
  count: CountInfo | null;
};

function parsePerf(p: unknown): LayerPerf | null {
  if (!p || typeof p !== "object") return null;
  const obj = p as Record<string, unknown>;
  if (typeof obj.latency_ms !== "number") return null;
  const cache = obj.cache_status;
  return {
    latency_ms: Math.round(obj.latency_ms),
    cache_status: typeof cache === "string" ? cache : null,
  };
}

function parseCount(c: unknown): CountInfo | null {
  if (!c || typeof c !== "object") return null;
  const obj = c as Record<string, unknown>;
  if (typeof obj.count !== "number") return null;
  return {
    count: obj.count,
    bounded: Boolean(obj.bounded),
    max_distance: typeof obj.max_distance === "number" ? obj.max_distance : 0,
    layer_perf: parsePerf(obj.layer_perf),
  };
}

const productCache = new Map<string, Product>();

export function cacheProduct(p: Product): void {
  productCache.set(p.asin, p);
}

export function getCachedProduct(asin: string): Product | undefined {
  return productCache.get(asin);
}

function asStr(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function parseNum(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((item): item is string => typeof item === "string") : [];
}

function asNumberRecord(v: unknown): Record<string, number> {
  if (!v || typeof v !== "object" || Array.isArray(v)) return {};
  return Object.fromEntries(
    Object.entries(v as Record<string, unknown>)
      .map(([key, value]) => [key, parseNum(value)] as const)
      .filter(([, value]) => value > 0),
  );
}

function asStringArrayRecord(v: unknown): Record<string, string[]> {
  if (!v || typeof v !== "object" || Array.isArray(v)) return {};
  return Object.fromEntries(
    Object.entries(v as Record<string, unknown>).map(([key, value]) => [
      key,
      asStringArray(value),
    ]),
  );
}

// Log the upstream response body to the Node-side pod logs but never thread
// it through to the thrown Error — Next.js server components surface
// Error.message into rendered UI on the search/product pages, and upstream
// 5xx bodies have been observed to carry sensitive bytes (auth headers,
// secret URLs). The Error message we throw is intentionally body-free.
async function logUpstreamFailure(label: string, res: Response): Promise<void> {
  const body = await res.text().catch(() => "");
  console.error(`[backend] ${label} upstream ${res.status}: ${body.slice(0, 500)}`);
}

async function fetchWithTimeout(
  input: Parameters<typeof fetch>[0],
  init: Parameters<typeof fetch>[1] = {},
  timeoutMs = DEFAULT_BACKEND_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (err) {
    if (controller.signal.aborted) {
      throw new Error(`backend request timed out after ${timeoutMs}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

export function hitToProduct(hit: BackendHit): Product {
  const a = hit.attributes ?? {};
  const asin = asStr(a.asin) || hit.id;
  return {
    asin,
    title: asStr(a.title),
    description: asStr(a.description),
    category: asStr(a.category),
    image_url: asStr(a.image_url),
    price: null,
    rating: parseNum(a.avg_rating_txt),
    rating_count: parseNum(a.rating_cnt_txt),
    tags: asStringArray(a.tags),
    tag_counts: asNumberRecord(a.tag_counts),
    tag_samples: asStringArrayRecord(a.tag_samples),
  };
}

export function attributesToProduct(asin: string, a: Record<string, unknown>): Product {
  const resolvedAsin = asStr(a.asin) || asin;
  return {
    asin: resolvedAsin,
    title: asStr(a.title),
    description: asStr(a.description),
    category: asStr(a.category),
    image_url: asStr(a.image_url),
    price: null,
    rating: parseNum(a.avg_rating_txt),
    rating_count: parseNum(a.rating_cnt_txt),
    tags: asStringArray(a.tags),
    tag_counts: asNumberRecord(a.tag_counts),
    tag_samples: asStringArrayRecord(a.tag_samples),
  };
}

export type SearchOptions = {
  topK?: number;
  tags?: string[];
  cursor?: string | null;
  withCount?: boolean;
  maxDistance?: number;
};

export async function backendSearch(
  query: string,
  options: SearchOptions = {},
): Promise<SearchResult> {
  if (!API_BASE) throw new Error("HEV_SHOP_API_BASE not set");
  const trimmed = query.trim();
  if (!trimmed) {
    return {
      products: [],
      layer_perf: null,
      stable_as_of: null,
      next_cursor: null,
      count: null,
    };
  }
  const { topK = 24, tags = [], cursor, withCount, maxDistance } = options;

  const payload: Record<string, unknown> = {
    query: trimmed,
    top_k: Math.min(topK, 200),
    tags,
  };
  if (cursor) payload.cursor = cursor;
  if (withCount) payload.with_count = true;
  if (typeof maxDistance === "number") payload.max_distance = maxDistance;

  const res = await fetchWithTimeout(`${API_BASE}/search`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-hev-shop-surface": "storefront",
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  if (!res.ok) {
    await logUpstreamFailure("search", res);
    throw new Error(`search upstream ${res.status}`);
  }
  const json = (await res.json()) as BackendSearchResponse;
  const products = json.hits.map(hitToProduct);
  for (const p of products) cacheProduct(p);
  return {
    products,
    layer_perf: parsePerf(json.layer_perf),
    stable_as_of: json.stable_as_of ?? null,
    next_cursor: json.next_cursor ?? null,
    count: parseCount(json.count),
  };
}

export async function backendProduct(asin: string): Promise<ProductWithPerf | null> {
  if (!API_BASE) throw new Error("HEV_SHOP_API_BASE not set");
  const res = await fetchWithTimeout(
    `${API_BASE}/product/${encodeURIComponent(asin)}`,
    { cache: "no-store" },
  );
  if (res.status === 404) return null;
  if (!res.ok) {
    await logUpstreamFailure("product", res);
    throw new Error(`product upstream ${res.status}`);
  }
  const json = (await res.json()) as BackendProductResponse;
  const product = attributesToProduct(json.asin, json.attributes ?? {});
  cacheProduct(product);
  return { product, layer_perf: parsePerf(json.layer_perf) };
}

export type DropInfo = {
  run_id: string;
  product_count: number;
  stable_as_of: number | null;
};

export type DropsResult = {
  drops: DropInfo[]; // newest first
  layer_perf: LayerPerf | null;
};

// GET /drops — recent nightly catalog runs (see docs/FRONTEND_0.1_DESIGN.md;
// endpoint lands with launch-plan WS4).
export async function backendDrops(): Promise<DropsResult> {
  if (!API_BASE) throw new Error("HEV_SHOP_API_BASE not set");
  const res = await fetchWithTimeout(
    `${API_BASE}/drops`,
    { cache: "no-store" },
    META_TIMEOUT_MS,
  );
  if (!res.ok) {
    await logUpstreamFailure("drops", res);
    throw new Error(`drops upstream ${res.status}`);
  }
  const json = (await res.json()) as {
    drops?: Array<Record<string, unknown>>;
    layer_perf?: unknown;
  };
  const drops = (json.drops ?? [])
    .filter((d) => typeof d.run_id === "string")
    .map((d) => ({
      run_id: d.run_id as string,
      product_count: parseNum(d.product_count),
      stable_as_of:
        typeof d.stable_as_of === "number" ? d.stable_as_of : null,
    }));
  return { drops, layer_perf: parsePerf(json.layer_perf) };
}

export type RecentSearchesResult = {
  queries: string[]; // newest first, deduped server-side
  layer_perf: LayerPerf | null;
};

// GET /search/recent — recent distinct queries from Layer search-history
// (raw_query via x-hevlayer-search-query; see docs/FRONTEND_0.1_DESIGN.md,
// endpoint lands with launch-plan WS5).
export async function backendRecentSearches(
  limit = 8,
): Promise<RecentSearchesResult> {
  if (!API_BASE) throw new Error("HEV_SHOP_API_BASE not set");
  const url = new URL(`${API_BASE}/search/recent`);
  url.searchParams.set("limit", String(limit));
  const res = await fetchWithTimeout(
    url,
    { cache: "no-store" },
    META_TIMEOUT_MS,
  );
  if (!res.ok) {
    await logUpstreamFailure("recent searches", res);
    throw new Error(`recent searches upstream ${res.status}`);
  }
  const json = (await res.json()) as {
    queries?: unknown[];
    layer_perf?: unknown;
  };
  const queries = (json.queries ?? []).filter(
    (value): value is string =>
      typeof value === "string" && value.trim().length > 0,
  );
  return { queries, layer_perf: parsePerf(json.layer_perf) };
}

export type CategoryBucket = {
  value: string;
  doc_count: number;
};

export type BackendMeta = {
  namespace: string;
  vectors: number;
  categories: CategoryBucket[];
  stable_as_of: number | null;
  is_stable: boolean;
  layer_perf: LayerPerf | null;
};

export async function backendMeta(): Promise<BackendMeta> {
  if (!API_BASE) throw new Error("HEV_SHOP_API_BASE not set");
  const res = await fetchWithTimeout(
    `${API_BASE}/meta`,
    { cache: "no-store" },
    META_TIMEOUT_MS,
  );
  if (!res.ok) {
    await logUpstreamFailure("meta", res);
    throw new Error(`meta upstream ${res.status}`);
  }
  const json = (await res.json()) as Omit<BackendMeta, "layer_perf"> & {
    layer_perf?: unknown;
  };
  return {
    namespace: json.namespace,
    vectors: json.vectors,
    categories: json.categories,
    stable_as_of: json.stable_as_of ?? null,
    is_stable: json.is_stable,
    layer_perf: parsePerf(json.layer_perf),
  };
}

export async function backendSimilar(
  asin: string,
  topK = 8,
): Promise<SearchResult> {
  if (!API_BASE) throw new Error("HEV_SHOP_API_BASE not set");
  const res = await fetchWithTimeout(`${API_BASE}/recommend`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ asin, top_k: Math.min(topK, 200) }),
    cache: "no-store",
  });
  if (!res.ok) {
    await logUpstreamFailure("recommend", res);
    throw new Error(`recommend upstream ${res.status}`);
  }
  const json = (await res.json()) as BackendRecommendResponse;
  const products = json.hits.map(hitToProduct);
  for (const p of products) cacheProduct(p);
  return {
    products,
    layer_perf: parsePerf(json.layer_perf),
    stable_as_of: json.stable_as_of ?? null,
    next_cursor: json.next_cursor ?? null,
    count: null,
  };
}

export type ReviewSearchOptions = {
  topK?: number;
  cursor?: string | null;
  withCount?: boolean;
  maxDistance?: number;
};

export async function backendReviewSearch(
  asin: string,
  query: string,
  options: ReviewSearchOptions = {},
): Promise<ReviewSearchResult> {
  if (!API_BASE) throw new Error("HEV_SHOP_API_BASE not set");
  const { topK = 8, cursor, withCount, maxDistance } = options;
  const url = new URL(`${API_BASE}/search/reviews`);
  url.searchParams.set("asin", asin);
  url.searchParams.set("q", query.trim() || "quality");
  url.searchParams.set("top_k", String(Math.min(topK, 200)));
  if (cursor) url.searchParams.set("cursor", cursor);
  if (withCount) url.searchParams.set("with_count", "true");
  if (typeof maxDistance === "number") {
    url.searchParams.set("max_distance", String(maxDistance));
  }
  const res = await fetchWithTimeout(url, { cache: "no-store" });
  if (!res.ok) {
    await logUpstreamFailure("review search", res);
    throw new Error(`review search upstream ${res.status}`);
  }
  const json = (await res.json()) as BackendSearchResponse;
  const reviews = json.hits.map((hit) => {
    const a = hit.attributes ?? {};
    return {
      id: hit.id,
      dist: hit.dist,
      review_id: asStr(a.review_id),
      asin: asStr(a.asin),
      chunk_idx: parseNum(a.chunk_idx),
      text_chunk: asStr(a.text_chunk),
      rating: a.rating == null ? null : parseNum(a.rating),
      title: asStr(a.title),
      helpful_vote: parseNum(a.helpful_vote),
    };
  });
  return {
    reviews,
    layer_perf: parsePerf(json.layer_perf),
    stable_as_of: json.stable_as_of ?? null,
    next_cursor: json.next_cursor ?? null,
    count: parseCount(json.count),
  };
}

export async function backendReviewSamples(
  asin: string,
  reviewIds: string[],
): Promise<ReviewSample[]> {
  if (!API_BASE || reviewIds.length === 0) return [];
  const url = new URL(`${API_BASE}/reviews/samples`);
  url.searchParams.set("asin", asin);
  url.searchParams.set("ids", reviewIds.join(","));
  const res = await fetchWithTimeout(url, { cache: "no-store" });
  if (!res.ok) return [];
  const json = (await res.json()) as { samples: ReviewSample[] };
  return json.samples ?? [];
}
