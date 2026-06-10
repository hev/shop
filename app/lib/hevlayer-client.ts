import { findByAsin } from "./mock-data";
import { similarProducts } from "./search";
import type { Product } from "./types";

// Stand-in for the hev layer TypeScript client. The real client now exists in
// the layer repo (clients/typescript, exported as the `hevlayer` package; older
// drafts assumed a scoped package name) but is not published to npm, so this
// mock still backs the rail for 0.1. It mirrors the method surface so the
// storefront adopts the real client as a near-drop-in once it publishes — same
// `searchById` shape; only the body swaps to gateway calls.
//
// Gateway-later swap (see docs/BROWSING_RAIL_DESIGN.md → "Gateway-later path"):
//   1. add `hevlayer` to package.json (file: path dep until npm publish);
//   2. construct `new Hevlayer({ baseURL, apiKey })` from LAYER_GATEWAY_URL /
//      LAYER_GATEWAY_API_KEY (the web pod already holds these);
//   3. implement searchById as: fetchDocument(seed) per seed to resolve its
//      vector, one multiQueryTurbopufferNamespace round trip with a
//      ["vector","ANN",vec] leg per seed, then the SAME RRF fusion below.
//   The signature does not change; fusion stays client-side (the point of
//   choosing multi-query over centroid).
//
// `searchById` powers "Similar to your browsing": given the array of products
// you've viewed, it returns one merged "more like these" rail. It models the
// gateway's **multi-query** overload (docs/api/query#multi-query): one
// nearest-neighbor query per seed, batched into a single round trip, then
// fused with reciprocal rank fusion (RRF).
//
// Why multi-query and not array `nearest_to_id` (centroid)? Centroid averages
// the seed vectors into one query and loses each seed's identity; multi-query
// keeps N independent rankings ("because you viewed X" *and* "because you
// viewed Y") and fuses them. Note the gateway caveat: multi-query does not
// resolve `nearest_to_id` per leg — each leg needs an explicit
// `["vector","ANN", <vec>]`, so the gateway build first resolves every seed's
// vector via fetch (NVMe cache), then issues the batch.
//
// This 0.1 build is mock-only: it fuses per-seed neighbor lists from the local
// catalog instead of touching the gateway. The header above is the contained
// swap path once the TypeScript client is available to the storefront build.

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
  // The seed IDs actually queried (deduped, unknown ASINs dropped).
  seeds: string[];
  // One ANN query leg per seed, batched into a single multi-query round trip.
  legs: number;
  perSeedTopK: number;
  // Size of the fused, deduped result set.
  fused: number;
};

export type SearchByIdResult = {
  products: Product[];
  expansion: ExpansionSummary;
};

// Reciprocal rank fusion constant. 60 is the value from the original RRF paper
// and the upstream default — large enough that deep ranks still contribute,
// small enough that the top of each leg dominates.
const RRF_K = 60;

export class HevlayerClient {
  constructor(private readonly namespace = "amazon-products") {}

  async searchById(
    ids: string[],
    options: SearchByIdOptions = {},
  ): Promise<SearchByIdResult> {
    const { topK = 8, perSeedTopK = 8 } = options;
    const seeds = dedupe(ids).filter((id) => findByAsin(id));
    const seedSet = new Set(seeds);

    // One ranking per seed. In the gateway build these are the legs of a single
    //   POST /v2/namespaces/{this.namespace}/query?stainless_overload=multiQuery
    //   { "queries": [ { "rank_by": ["vector","ANN", <seed vec>], "top_k": … }, … ] }
    // call — after resolving each seed's vector via fetch, since multi-query
    // does not expand `nearest_to_id` per leg. The gateway returns a parallel
    // `results` array (one ranking per leg) that we fuse below.
    // Gateway build: replace this with fetchDocument(seed) per seed + one
    // multiQueryTurbopufferNamespace round trip (see header "Gateway-later swap").
    const legs = seeds.map((seed) => similarProducts(seed, perSeedTopK));

    const products = fuseRRF(legs, seedSet, topK);
    return {
      products,
      expansion: {
        strategy: "multi-query",
        fusion: "rrf",
        seeds,
        legs: seeds.length,
        perSeedTopK,
        fused: products.length,
      },
    };
  }
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
      if (exclude.has(p.asin)) return;
      byId.set(p.asin, p);
      score.set(p.asin, (score.get(p.asin) ?? 0) + 1 / (RRF_K + rank + 1));
    });
  }
  return [...score.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([asin]) => byId.get(asin)!);
}
