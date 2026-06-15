import { Hevlayer } from "hevlayer";
import type { Product } from "./types";

// "Similar to your browsing" runs on the real hev layer TypeScript client
// (`hevlayer`, vendored in-tree at app/vendor/hevlayer until it publishes to
// npm; refresh with scripts/sync-ts-client.sh). `searchById` is the array
// expansion of the single-seed `/recommend` path: hand the client the products
// you've viewed and get one merged "more like these" rail.
//
// It models the gateway's **multi-query** overload (docs/api/query#multi-query):
// one nearest-neighbor query per viewed product, batched into a single round
// trip, then fused client-side with reciprocal rank fusion (RRF). Each leg uses
// the Layer `nearest_to_id` single-query shape — the gateway resolves each
// seed's stored vector per leg before it goes upstream (docs/api/query, "A leg
// may use … the Layer vector / nearest_to_id single-query shape; nearest_to_id
// is resolved before the leg is sent upstream"), so the web pod never has to
// fetch and ship 768-d vectors itself.
//
// Why multi-query and not array `nearest_to_id` (centroid)? Centroid averages
// the seed vectors into one query and loses each seed's identity; multi-query
// keeps N independent rankings ("because you viewed X" *and* "because you
// viewed Y") and fuses them. RRF is why fusion stays client-side — it's the
// point of choosing multi-query over centroid.
//
// Strategic constraint ([[project-strategic-goals]]): the storefront talks to
// Layer only, never a direct turbopuffer client — the gateway adds the doc
// cache and the `_upserted_at` freshness watermark this app depends on. So the
// client is built with `fallbackToTurbopuffer: false`: a gateway outage fails
// the rail (which degrades to invisible) rather than silently bypassing Layer.

const GATEWAY_URL = process.env.LAYER_GATEWAY_URL ?? "";
const GATEWAY_API_KEY = (process.env.LAYER_GATEWAY_API_KEY ?? "").trim();
const PRODUCT_NAMESPACE =
  process.env.LAYER_PRODUCT_NAMESPACE ?? "amazon-products";

// Attributes we map into a Product card — mirrors the search service's
// hitToProduct contract (search/ returns avg_rating_txt / rating_cnt_txt and
// no price). Requesting an explicit list keeps the multi-query payload tight.
const PRODUCT_ATTRIBUTES = [
  "asin",
  "title",
  "description",
  "category",
  "image_url",
  "avg_rating_txt",
  "rating_cnt_txt",
];

// The gateway accepts 2..16 legs per multi-query batch. The rail caps seeds at
// 6 upstream; clamp here too so a longer history can't 422 the batch.
const MAX_LEGS = 16;

export type SearchByIdOptions = {
  // How many fused results to return.
  topK?: number;
  // How deep to read each seed's ranking before fusing.
  perSeedTopK?: number;
  namespace?: string;
};

export type ExpansionSummary = {
  strategy: "multi-query";
  fusion: "rrf";
  // The seed IDs actually queried (deduped).
  seeds: string[];
  // One ANN query leg per seed, batched into a single multi-query round trip.
  legs: number;
  perSeedTopK: number;
  // Size of the fused, deduped result set.
  fused: number;
};

// Gateway round-trip signal for the multi-query batch, shaped like the rest of
// the app's perf badges (see lib/backend.ts).
export type LayerPerf = {
  latency_ms: number;
  cache_status: string | null;
};

export type SearchByIdResult = {
  products: Product[];
  expansion: ExpansionSummary;
  layer_perf: LayerPerf | null;
};

// Reciprocal rank fusion constant. 60 is the value from the original RRF paper
// and the upstream default — large enough that deep ranks still contribute,
// small enough that the top of each leg dominates.
const RRF_K = 60;

// Whether the gateway-direct path is configured. Locally this needs both
// LAYER_GATEWAY_URL and LAYER_GATEWAY_API_KEY in .env.local; the prod web pod
// holds both already. When false the rail degrades to invisible.
export function browsingClientEnabled(): boolean {
  return GATEWAY_URL.length > 0 && GATEWAY_API_KEY.length > 0;
}

let singleton: Hevlayer | null = null;

function gateway(): Hevlayer {
  if (!singleton) {
    singleton = new Hevlayer({
      baseUrl: GATEWAY_URL,
      apiKey: GATEWAY_API_KEY,
      // Layer-only: never fall through to a direct turbopuffer client.
      fallbackToTurbopuffer: false,
    });
  }
  return singleton;
}

export class HevlayerClient {
  constructor(private readonly namespace = PRODUCT_NAMESPACE) {}

  async searchById(
    ids: string[],
    options: SearchByIdOptions = {},
  ): Promise<SearchByIdResult> {
    const { topK = 8, perSeedTopK = 8 } = options;
    const namespace = options.namespace ?? this.namespace;
    const seeds = dedupe(ids).slice(0, MAX_LEGS);

    // A union needs at least two seeds; below that there is nothing to fuse.
    // (The product page's single-seed "Visually similar" rail covers one seed.)
    if (seeds.length < 2 || !browsingClientEnabled()) {
      return emptyResult(seeds, perSeedTopK);
    }

    // One leg per seed, batched into a single multi-query round trip:
    //   POST /v2/namespaces/{ns}/query?stainless_overload=multiQuery
    //   { "queries": [ { "nearest_to_id": ["<seed>"], "top_k": … }, … ] }
    // The gateway resolves each seed's stored vector per leg and returns a
    // parallel `results` array (one ranking per leg) that we fuse below. Each
    // leg filters out its own seed so a product never recommends itself.
    const body: Record<string, unknown> = {
      queries: seeds.map((seed) => ({
        nearest_to_id: [seed],
        top_k: perSeedTopK,
        include_attributes: PRODUCT_ATTRIBUTES,
        filters: ["id", "NotEq", seed],
      })),
    };

    const batch = await gateway().multiQueryTurbopufferNamespace(
      namespace,
      body,
      { withPerf: true },
    );

    const results = Array.isArray(batch.data.results) ? batch.data.results : [];
    const legs = results.map((leg) => rowsToProducts(leg.rows ?? []));
    const products = fuseRRF(legs, new Set(seeds), topK);

    return {
      products,
      expansion: {
        strategy: "multi-query",
        fusion: "rrf",
        seeds,
        legs: legs.length,
        perSeedTopK,
        fused: products.length,
      },
      layer_perf: {
        latency_ms: Math.round(batch.perf.latencyMs),
        cache_status: batch.perf.cacheStatus,
      },
    };
  }
}

function emptyResult(seeds: string[], perSeedTopK: number): SearchByIdResult {
  return {
    products: [],
    expansion: {
      strategy: "multi-query",
      fusion: "rrf",
      seeds,
      legs: 0,
      perSeedTopK,
      fused: 0,
    },
    layer_perf: null,
  };
}

function dedupe(ids: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of ids) {
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

function asStr(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function asNum(v: unknown): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

// A multi-query row is turbopuffer-shaped: top-level `id`, `$dist`, and the
// requested attributes flattened alongside them. Mirrors the search service's
// hitToProduct so cards render identically to /search and /recommend results.
function rowsToProducts(rows: Record<string, unknown>[]): Product[] {
  return rows.map((row) => {
    const asin = asStr(row.asin) || asStr(row.id);
    return {
      asin,
      title: asStr(row.title),
      description: asStr(row.description),
      category: asStr(row.category),
      image_url: asStr(row.image_url),
      price: null,
      rating: asNum(row.avg_rating_txt),
      rating_count: asNum(row.rating_cnt_txt),
    };
  });
}

// Reciprocal rank fusion: a document's score is the sum, over every leg it
// appears in, of 1 / (RRF_K + rank). A product that ranks high for several of
// your viewed seeds beats one that ranks high for a single seed — which is
// exactly the "across what you've been browsing" signal the rail wants. Seeds
// themselves are excluded.
function fuseRRF(
  legs: Product[][],
  exclude: Set<string>,
  limit: number,
): Product[] {
  const score = new Map<string, number>();
  const byId = new Map<string, Product>();
  for (const leg of legs) {
    leg.forEach((p, rank) => {
      if (!p.asin || exclude.has(p.asin)) return;
      byId.set(p.asin, p);
      score.set(p.asin, (score.get(p.asin) ?? 0) + 1 / (RRF_K + rank + 1));
    });
  }
  return [...score.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([asin]) => byId.get(asin)!);
}
