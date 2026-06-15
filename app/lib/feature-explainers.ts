// Central registry for the storefront's "How it works" explainers.
//
// Every Layer-powered result set on the site gets a `<FeatureExplainer id=…>`
// pill in its section header; the popover content comes from here. Keeping the
// copy in one registry (rather than inline per surface) is what makes the
// pattern broad: adding the affordance to a new surface is one entry + one
// `<FeatureExplainer />`, and the mechanism/doc-link vocabulary stays
// consistent across search, recommendations, drops, and reads.
//
// Branding: "hev layer" in prose, `hevlayer`/`@hevlayer` only for literal
// identifiers (package names, headers, fields).

const DOCS = "https://hevlayer.com/docs";

export type DocLink = { label: string; href: string };

// One mechanism row: a short label and a mono detail (a field, call shape, or
// model name). Rendered as a definition list in the popover.
export type Mechanism = { label: string; detail: string };

export type FeatureExplainer = {
  id: string;
  // Popover header — the feature's name, e.g. "Similar to your browsing".
  title: string;
  // Plain-language summary, 1–2 sentences. No jargon the popover doesn't then
  // unpack in `mechanism`.
  summary: string;
  mechanism: Mechanism[];
  // Optional gateway call shape, rendered mono. Keep it short.
  call?: string;
  docs: DocLink[];
};

const EXPLAINERS: Record<string, FeatureExplainer> = {
  "browsing-rail": {
    id: "browsing-rail",
    title: "Similar to your browsing",
    summary:
      "Runs one nearest-neighbor query for each product you've viewed this session, batched into a single multi-query round trip, then fuses the rankings with reciprocal rank fusion (RRF).",
    mechanism: [
      { label: "TS client", detail: "searchById([...ids])" },
      { label: "Multi-query", detail: "one ANN leg per viewed product" },
      { label: "Fusion", detail: "reciprocal rank fusion (RRF)" },
    ],
    call:
      'POST /v2/namespaces/amazon-products/query?stainless_overload=multiQuery\n{ "queries": [ { "nearest_to_id": ["<asin>"] }, … ] }',
    docs: [
      { label: "Multi-query", href: `${DOCS}/api/query#multi-query` },
      { label: "Query by id", href: `${DOCS}/api/query#query-by-id` },
    ],
  },
  "visually-similar": {
    id: "visually-similar",
    title: "Visually similar",
    summary:
      "Ranks the catalog by nearest neighbors to this product's stored image vector. Query-by-id means the gateway looks up the seed vector for you, so it's one call — no need to send the vector.",
    mechanism: [
      { label: "Embedding", detail: "CLIP ViT-L/14 · 768d" },
      { label: "Query by id", detail: 'nearest_to_id: "<asin>"' },
      { label: "Metric", detail: "cosine" },
    ],
    call:
      'POST /v2/namespaces/amazon-products/query\n{ "nearest_to_id": "<asin>", "top_k": 8 }',
    docs: [{ label: "Query by id", href: `${DOCS}/api/query#query-by-id` }],
  },
  search: {
    id: "search",
    title: "Vector search",
    summary:
      "Your text is embedded with CLIP and matched against product image vectors by cosine distance. The read pins to a freshness watermark so the result set reflects one consistent snapshot.",
    mechanism: [
      { label: "Embedding", detail: "CLIP text encoder → 768d" },
      { label: "Rank by", detail: '["vector","ANN", <query vec>]' },
      { label: "Stable read", detail: "stable_as_of watermark" },
    ],
    call:
      'POST /v2/namespaces/amazon-products/query\n{ "rank_by": ["vector","ANN", …], "top_k": 48 }',
    docs: [
      { label: "Query & Fetch", href: `${DOCS}/api/query` },
      { label: "Stable reads", href: `${DOCS}/api/query#stable-reads` },
    ],
  },
  // --- Registry entries staged for the next wave of the rollout (see
  // docs/FEATURE_EXPLAINERS.md). Content is ready; the `<FeatureExplainer />`
  // mounts land with each surface.
  "product-fetch": {
    id: "product-fetch",
    title: "Cached document fetch",
    summary:
      "Product detail reads go through Layer's pull-through document cache. A cache hit serves the row from Aerospike without touching turbopuffer; warm jobs and prior reads populate it.",
    mechanism: [
      { label: "Fetch", detail: "GET …/documents/{asin}" },
      { label: "Cache", detail: "Aerospike pull-through · x-layer-cache" },
    ],
    docs: [
      { label: "Fetch", href: `${DOCS}/api/query#fetch` },
      { label: "Warm cache", href: `${DOCS}/api/warm-cache` },
    ],
  },
  drops: {
    id: "drops",
    title: "Nightly drops",
    summary:
      "Each drop is one nightly catalog run re-embedded end to end. The freshness watermark tells you which consistent snapshot a drop's vectors belong to.",
    mechanism: [
      { label: "Pipeline", detail: "extract-chunk → embed → indexed" },
      { label: "Snapshot", detail: "field: catalog_run_id" },
      { label: "Freshness", detail: "stable_as_of · is_stable" },
    ],
    docs: [
      { label: "Snapshots", href: `${DOCS}/api/snapshots` },
      { label: "Pipelines", href: `${DOCS}/api/pipelines` },
      { label: "Guarantees", href: `${DOCS}/guarantees` },
    ],
  },
  categories: {
    id: "categories",
    title: "Category facets",
    summary:
      "Category chips come from a field-value snapshot gated on the freshness watermark, alongside the namespace's row count.",
    mechanism: [
      { label: "Snapshot", detail: "field: category" },
      { label: "Metadata", detail: "approx_row_count" },
    ],
    docs: [
      { label: "Snapshots", href: `${DOCS}/api/snapshots` },
      { label: "Namespace metadata", href: `${DOCS}/api/namespace-metadata` },
    ],
  },
  // RFC 0040 — the aggregate counterpart to the personal "recent searches"
  // dropdown. Mounted on the homepage Trending section (Trending.tsx); the
  // `stat` passed at the mount reflects mode (frequency vs quality) so this
  // never claims a quality signal Phase 1 isn't computing.
  trending: {
    id: "trending",
    title: "Trending searches",
    summary:
      "The queries everyone runs, aggregated on a schedule by a Layer reduce UDF and materialized into a small namespace the homepage reads in one cheap, freshness-stamped query. Ranked by volume — and, once click attribution is on, by how good each query's results were (NDCG).",
    mechanism: [
      { label: "Source", detail: "search-history (+ clickstream)" },
      { label: "Reduce", detail: "scheduled UDF → amazon-products-trending" },
      { label: "Rank", detail: "volume × NDCG (W)" },
    ],
    docs: [
      { label: "Search history", href: `${DOCS}/api/search-history` },
      { label: "Functions (UDFs)", href: `${DOCS}/kubernetes/function-crd` },
    ],
  },
};

export function getFeatureExplainer(id: string): FeatureExplainer | undefined {
  return EXPLAINERS[id];
}
