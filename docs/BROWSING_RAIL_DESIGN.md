# Browsing rail — "Similar to your browsing"

Design notes for the homepage rail seeded by what you've viewed this session.
This is the build-out of the reserved slot in `FRONTEND_0.1_DESIGN.md` §3
(issue #7), unblocked by array `searchById` on the hev layer TypeScript client.

The implementation lives in `app/components/BrowsingRail.tsx`,
`app/components/RecordView.tsx`, `app/lib/recently-viewed.ts`,
`app/lib/hevlayer-client.ts`, `app/lib/browsing.ts`, and
`app/app/api/browsing/route.ts`.

Design constraints carried over from `CLAUDE.md` / `FRONTEND_0.1_DESIGN.md`:

- Product affordance first, pipeline evidence second. This is a real
  recommendation rail; the gateway mechanics stay in the supporting register.
- Personalized surfaces degrade to *invisible*: no empty-state placeholder on
  the homepage when there is no history, no result, or no client.

## What it showcases

The differentiating surface here is the **hev layer TypeScript client**.
`/recommend` already does single-seed visual similarity through the Python
SDK's `nearest_to_id`. The browsing rail is the **array expansion** of that
idea: hand the client *several* product IDs — your browsing history — and get
back one merged neighbor set. The interesting line of code is:

```ts
const { products } = await client.searchById(viewedAsins, { topK: 8 });
```

## Decisions (0.1)

| Fork | Choice | Why |
| ---- | ------ | --- |
| **Placement** | Homepage | The rail is a *session-wide* taste signal, strongest where there is no single seed product. It's the first thing a returning shopper sees. |
| **Expansion** | **Multi-query + RRF** | `searchById` issues one nearest-neighbor query per viewed product as the legs of a single [multi-query](https://hevlayer.com/docs/api/query#multi-query) round trip, then fuses the parallel rankings with reciprocal rank fusion. Reads as "because you viewed X **and** Y" and rewards products that rank for several seeds. (Alternative — array `nearest_to_id`, which averages the seed vectors into one centroid ranking — collapses each seed's identity; reach for it when you want one blended "more like these" instead of fused independent rankings.) |
| **TS client** | **Gateway-backed** | `HevlayerClient.searchById` drives the real `hevlayer` TS client (a `file:` dep on `../../layer/clients/typescript`) against the prod gateway from the web pod. Built with `fallbackToTurbopuffer: false` to honor the Layer-only constraint. |
| **Per-leg seed** | **`nearest_to_id`** | Each multi-query leg is `{ "nearest_to_id": ["<asin>"] }`; the gateway resolves each seed's stored vector per leg before it goes upstream, so the web pod never fetches or ships 768-d vectors. (Earlier drafts assumed multi-query couldn't resolve `nearest_to_id` per leg and pre-fetched each vector — the gateway now does, verified against prod 2026-06-15.) |

## Browsing history (the array of IDs)

`app/lib/recently-viewed.ts` keeps a localStorage list of the products you've
opened, newest first, deduped, capped at 12. No account, no server round-trip.

- `RecordView` (mounted on `/product/[asin]`) pushes the current product on
  view and fires a `RECENTLY_VIEWED_EVENT` on the window.
- Only `{ asin, title, image_url, category }` is persisted — enough to render,
  and the ASIN is what we actually send upstream. The rail sends *ids*; the
  client re-hydrates neighbors.

## Multi-query + RRF

`HevlayerClient.searchById(ids, { topK, perSeedTopK })`:

1. Dedupe `ids`, cap at 16 (the gateway's per-batch leg limit) → `seeds`. Need
   ≥2 to fuse; below that the rail returns empty.
2. Read each seed's top `perSeedTopK` neighbors as one leg. The legs are
   batched into a single multi-query round trip
   (`POST …/query?stainless_overload=multiQuery`), each leg a
   `{ "nearest_to_id": ["<asin>"], "filters": ["id","NotEq","<asin>"] }`; the
   gateway returns a parallel `results` array — one ranking per leg.
3. Fuse the legs with reciprocal rank fusion (RRF): a product's score is the
   sum over the legs it appears in of `1 / (60 + rank)`. Drop the seeds, take
   `topK`.

RRF (rather than concatenate-then-sort, or round-robin) is deliberate: a
product that ranks well for *several* of your viewed seeds beats one that ranks
well for a single seed — which is exactly the "across what you've been
browsing" signal the rail wants, and it needs no comparable distance scale
between legs.

**Per-leg `nearest_to_id`.** A multi-query leg may use the Layer
`nearest_to_id` single-query shape; the gateway resolves each seed's stored
vector per leg before sending it upstream (docs/api/query). So the web pod
hands the gateway *ids*, not vectors — no `fetch`-then-`["vector","ANN", …]`
two-step. (Verified against prod 2026-06-15; earlier drafts assumed multi-query
couldn't resolve `nearest_to_id` per leg.) The single-query niceties
(stable-read watermark, search-history capture, pagination) don't apply to
multi-query legs — fine here, since this rail is a "more like these" surface,
not a consistency-sensitive read. If a seed's vector can't be resolved (a stale
localStorage ASIN), the gateway 404s the whole batch and the route degrades the
rail to invisible.

## Response contract consumed by the frontend

```jsonc
// GET /api/browsing?ids=B07XYAA111,B08AAA222B&limit=8
{
  "seeds": ["B07XYAA111", "B08AAA222B"],
  "results": [ /* Product[] */ ],
  "expansion": {
    "strategy": "multi-query",
    "fusion": "rrf",
    "seeds": ["B07XYAA111", "B08AAA222B"],
    "legs": 2,
    "perSeedTopK": 8,
    "fused": 8
  },
  "took_ms": 168,
  "source": "gateway",
  "layer_perf": { "latency_ms": 166, "cache_status": null }
}
```

The rail renders nothing unless there are ≥2 seeds and ≥1 result. The
`expansion` summary plus `layer_perf` drive the "How it works" popover's live
stat: `3 queries → RRF → 8 results · 166ms`.

## Files

- `app/lib/recently-viewed.ts` — localStorage history + change event
- `app/components/RecordView.tsx` — records a view on the product page
- `app/lib/hevlayer-client.ts` — real `hevlayer` TS client wrapper (`searchById` multi-query + RRF)
- `app/lib/browsing.ts` — typed `/api/browsing` adapter
- `app/app/api/browsing/route.ts` — drives the client server-side
- `app/components/BrowsingRail.tsx` — homepage rail (client component)
- `app/app/page.tsx` — mounts the rail under the drop band

## Gateway path (shipped 2026-06-15)

The rail runs against the prod gateway through the real `hevlayer` TS client:

1. `hevlayer` is vendored in-tree at `app/vendor/hevlayer` (with its built
   `dist/`) and consumed as a `file:vendor/hevlayer` dep until it publishes to
   npm. Refresh it from the sibling checkout with `scripts/sync-ts-client.sh`.
2. `app/lib/hevlayer-client.ts` constructs `new Hevlayer({ baseUrl, apiKey })`
   from `LAYER_GATEWAY_URL` + `LAYER_GATEWAY_API_KEY`, with
   `fallbackToTurbopuffer: false` (Layer-only constraint). `searchById` issues
   one `multiQueryTurbopufferNamespace` round trip with a `nearest_to_id` leg
   per seed, maps the rows to `Product` (mirroring the search service's
   `hitToProduct`), and fuses client-side with the same RRF.
3. The route surfaces the multi-query `layer_perf`; the rail shows it in the
   "How it works" stat.

The gateway read path is **authenticated** — `LAYER_GATEWAY_API_KEY` is required
for the rail (local `.env.local` reads it from the `layer-turbopuffer`
credential in 1Password). When the key is absent the rail degrades to invisible.

## Web image packaging

`next build` bundles the `hevlayer` client straight into the route handler, so
the runtime image needs no `node_modules/hevlayer` — only build-time resolution.
The client is **vendored in-tree** (`app/vendor/hevlayer`, `file:vendor/hevlayer`)
rather than injected from the sibling checkout like the Python services'
`layer_client` build context. The reason is npm-specific: npm bakes a `file:`
link's *relative path* into the lockfile, and the sibling's `../../layer/...`
escapes the image filesystem root from `/app`, which `npm ci` rejects. An
in-tree link is portable. `app/Dockerfile` copies `vendor/` before `npm ci`
(pinned to npm 11 to match the lockfile generator; `node:22-alpine` ships 10).
