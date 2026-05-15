# hev-shop search API — frontend integration

How to point `web` at the deployed CLIP search backend instead
of the in-process mock scorer in `lib/search.ts`.

## Endpoint

```
POST {API_BASE}/search
Content-Type: application/json
```

The API runs as `hev-shop-api` in the `hev-shop` namespace on the
`mesh-bench` EKS cluster. There is **no public ingress yet** — reach it
via `kubectl port-forward` or from inside the cluster.

Inside-cluster URL (for a Next.js app deployed in the same cluster):
```
http://hev-shop-api.hev-shop.svc.cluster.local:8080
```

Local dev port-forward:
```
kubectl port-forward -n hev-shop svc/hev-shop-api 8090:8080
# → API_BASE=http://127.0.0.1:8090
```

## Request

```ts
type SearchRequest = {
  query: string;                  // required, non-empty
  top_k?: number;                 // default 10, max 200
  namespace?: string;             // default "amazon-products"
  include_attributes?: string[];  // override default attr list
  category?: string;              // optional exact category filter
  tags?: string[];                // optional review-derived tag filter
};
```

Default `include_attributes` returned by the server:

```
asin, title, description, category, image_url, avg_rating_txt, rating_cnt_txt,
tags, tag_counts, tag_samples
```

> `price` is **not** in the turbopuffer schema today. Passing it in
> `include_attributes` will 502. Same for any attribute not produced by
> `vector_attributes()` in the indexer.

## Response

```ts
type SearchResponse = {
  query: string;
  namespace: string;
  hits: SearchHit[];
  stable_as_of?: number;            // epoch-ms; see "Freshness" below
};

type SearchHit = {
  id: string;                       // ASIN
  dist: number | null;              // cosine distance, lower = closer
  attributes: Record<string, unknown>;
};
```

Real example (`{"query":"gaming laptop","top_k":3}`):

```json
{
  "query": "gaming laptop",
  "namespace": "amazon-products",
  "stable_as_of": 1747100000000,
  "hits": [
    {
      "id": "B01H40LA6Q",
      "dist": 0.75865257,
      "attributes": {
        "asin": "B01H40LA6Q",
        "title": "CUK HP Pavilion 17 Touch Gaming Notebook ...",
        "category": "Electronics",
        "image_url": "https://m.media-amazon.com/images/I/61TonVMnqKL._AC_SL1200_.jpg",
        "avg_rating_txt": "3.0",
        "rating_cnt_txt": "6"
      }
    }
  ]
}
```

### Freshness (`stable_as_of`)

The gateway runs queries at `consistency=eventual` and rewrites them with an
`_upserted_at <= watermark` filter, where `watermark` is the most recent
moment its consistency watcher saw the namespace fully indexed
(`unindexed_bytes == 0`). That watermark is echoed back as `stable_as_of`
(epoch ms).

- **Present**: the hits reflect everything indexed at or before that
  timestamp. Anything written after it is intentionally invisible to this
  query — it will appear once the watcher advances the watermark.
- **Absent (`null` / missing)**: the watcher hasn't yet observed a clean
  snapshot for this namespace (typical right after a deploy or a fresh
  namespace). Results still come back, but no freshness guarantee is
  attached.

UI: render as "results as of HH:MM:SS" or similar when present. Don't
surface staleness when absent — just omit the line.

## Wiring it into the Next.js app

The current `app/api/search/route.ts` calls the deployed API when
`HEV_SHOP_API_BASE` is set and falls back to `searchProducts()` mock data
otherwise. The server-side fetch shape is:

```ts
// app/api/search/route.ts
import { NextResponse } from "next/server";
import type { Product } from "@/lib/types";

export const runtime = "nodejs";

const API_BASE = process.env.HEV_SHOP_API_BASE!; // set in env

export async function GET(req: Request) {
  const url = new URL(req.url);
  const q = url.searchParams.get("q") ?? "";
  const limit = Number(url.searchParams.get("limit") ?? 24);

  const t0 = performance.now();
  const upstream = await fetch(`${API_BASE}/search`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query: q, top_k: limit }),
    cache: "no-store",
  });
  if (!upstream.ok) {
    return NextResponse.json(
      { error: `search upstream ${upstream.status}` },
      { status: 502 },
    );
  }
  const body = await upstream.json();
  const results: Product[] = body.hits.map(toProduct);
  return NextResponse.json({
    query: q,
    results,
    took_ms: Math.round(performance.now() - t0),
    // Pass through the gateway's consistency watermark (epoch ms) so the
    // page can render "results as of …". Omit when absent — see "Freshness".
    stable_as_of: body.stable_as_of ?? null,
  });
}

function toProduct(hit: any): Product {
  const a = hit.attributes ?? {};
  return {
    asin: hit.id,
    title: String(a.title ?? ""),
    description: String(a.description ?? ""),
    category: String(a.category ?? ""),
    image_url: String(a.image_url ?? ""),
    price: 0, // not available in backend yet (see "Schema gaps" below)
    rating: a.avg_rating_txt ? Number(a.avg_rating_txt) : 0,
    rating_count: a.rating_cnt_txt ? Number(a.rating_cnt_txt) : 0,
  };
}
```

For `/api/similar`, see "Similarity search" below — it needs a small
addition on the backend.

## Schema gaps vs. `lib/types.ts`

| `Product` field | Backend attribute        | Notes                          |
|-----------------|--------------------------|--------------------------------|
| `asin`          | `hit.id` / `asin`        | ASIN                           |
| `title`         | `title`                  |                                |
| `description`   | `description`            |                                |
| `category`      | `category`               | Amazon Reviews metadata category |
| `image_url`     | `image_url`              | hi-res or large Amazon CDN URL |
| `price`         | —                        | **not indexed**; treat as 0    |
| `rating`        | `avg_rating_txt` (string)| parse to number                |
| `rating_count`  | `rating_cnt_txt` (string)| parse to number                |
| `tags`          | `tags` (`string[]`)      | review classifier rollup      |
| `tag_counts`    | `tag_counts`             | per-tag support count         |
| `tag_samples`   | `tag_samples`            | review IDs for quote lookup   |

The rating fields are strings in turbopuffer because the namespace schema
is locked to stable string types — parse on the client.

## Review search and tag samples

Review chunks live in hash-sharded namespaces. The API resolves the shard from
ASIN and applies an ASIN filter to every query:

```bash
curl -sS 'http://127.0.0.1:8090/search/reviews?asin=B0123&q=battery&top_k=5' | jq .
```

Response shape matches `SearchResponse`; hits return review attributes such as
`review_id`, `chunk_idx`, `text_chunk`, `rating`, and `helpful_vote`.

Tag sample review IDs from product attributes can be expanded into snippets:

```bash
curl -sS 'http://127.0.0.1:8090/reviews/samples?asin=B0123&ids=r1,r2' | jq .
```

## Latency

Loaded from a port-forward against the live deploy:

- First request after a pod restart: ~10s (lazy CLIP model load + first
  text encode). Same pod stays warm afterwards.
- Warm request, `top_k=10`: ~250–350ms end-to-end. CLIP text encode is the
  dominant cost on the API's 2-CPU pod; turbopuffer query is <50ms.

Cold restarts happen on rollouts. If first-request latency matters for
your UX, fire a warmup query during page bootstrap.

## Auth, CORS, rate limits

None today. The pod listens on plain HTTP inside the cluster. Treat the
URL as internal. If the Next app calls this from a server route (as in
the sketch above) you don't need CORS; if you ever call it from the
browser, we'll need to add an ingress + CORS.

## Errors

| Status | Meaning                                                |
|--------|--------------------------------------------------------|
| 422    | Pydantic validation (empty `query`, `top_k` out of range) |
| 500    | API exception — check `kubectl logs deploy/hev-shop-api -n hev-shop` |
| 502    | Upstream layer-gateway / turbopuffer error (bad attribute, dim mismatch, etc.) |

The API returns `{detail: ...}` for 422, plain `Internal Server Error`
for 500 today. Worth handling both as "search unavailable" on the UI
side rather than surfacing the raw status.

## Similarity search (`/api/similar`)

Not yet implemented on the backend. Two options when you need it:

1. **Fetch-by-id then query**: add a "get vector by id" endpoint to the
   indexer that pulls the vector from turbopuffer and re-queries with it.
2. **Re-embed by title**: as a stopgap, look up the seed product's title
   and POST it as a `/search` query. Cheap and good enough for a demo.

Flag this to the backend team (Adam) when you start on similar — option 1
is the right long-term shape.

## Sanity check

From your laptop with the port-forward running:

```bash
curl -sS -X POST http://127.0.0.1:8090/search \
  -H 'content-type: application/json' \
  -d '{"query":"wireless headphones","top_k":3}' | jq .
```

Should return three earbud/headphone hits. If it returns 502 with a
turbopuffer error mentioning an attribute, you've passed an
`include_attributes` value not in the schema.
