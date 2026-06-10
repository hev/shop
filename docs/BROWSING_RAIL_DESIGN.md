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

The differentiating surface here is the **hev layer TypeScript client** (under
development). `/recommend` already does single-seed visual similarity through
the Python SDK's `nearest_to_id`. The browsing rail is the **array expansion**
of that idea: hand the client *several* product IDs — your browsing history —
and get back one merged neighbor set. The interesting line of code is:

```ts
const { products } = await client.searchById(viewedAsins, { topK: 8 });
```

## Decisions (0.1)

| Fork | Choice | Why |
| ---- | ------ | --- |
| **Placement** | Homepage | The rail is a *session-wide* taste signal, strongest where there is no single seed product. It's the first thing a returning shopper sees. |
| **Expansion** | **Multi-query + RRF** | `searchById` issues one nearest-neighbor query per viewed product as the legs of a single [multi-query](https://hevlayer.com/docs/api/query#multi-query) round trip, then fuses the parallel rankings with reciprocal rank fusion. Reads as "because you viewed X **and** Y" and rewards products that rank for several seeds. (Alternative — array `nearest_to_id`, which averages the seed vectors into one centroid ranking — collapses each seed's identity; reach for it when you want one blended "more like these" instead of fused independent rankings.) |
| **TS client** | **Mock-only** | The client surface is real (`HevlayerClient.searchById`); the body unions over the local catalog instead of calling the gateway. Drop-in swap when the `hevlayer` package is available to the storefront build. |

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

1. Dedupe `ids`, drop unknown ASINs → `seeds`.
2. Read each seed's top `perSeedTopK` neighbors as one leg. In the gateway
   build these legs are batched into a single multi-query round trip
   (`POST …/query?stainless_overload=multiQuery`), and the gateway returns a
   parallel `results` array — one ranking per leg.
3. Fuse the legs with reciprocal rank fusion (RRF): a product's score is the
   sum over the legs it appears in of `1 / (60 + rank)`. Drop the seeds, take
   `topK`.

RRF (rather than concatenate-then-sort, or round-robin) is deliberate: a
product that ranks well for *several* of your viewed seeds beats one that ranks
well for a single seed — which is exactly the "across what you've been
browsing" signal the rail wants, and it needs no comparable distance scale
between legs.

**Gateway caveat (multi-query).** The docs are explicit that multi-query does
**not** resolve `nearest_to_id` per leg — each leg needs an explicit
`["vector","ANN", <vec>]`. So the gateway build first resolves every seed's
stored vector via [fetch](https://hevlayer.com/docs/api/query#fetch) (NVMe
cache, cheap on a hit), then issues the batch. The single-query niceties
(stable-read watermark, search-history capture, pagination) don't apply to
multi-query legs — fine here, since this rail is a "more like these" surface,
not a consistency-sensitive read.

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
  "took_ms": 1,
  "source": "mock",
  "layer_perf": null   // gateway build fills the multi-query round-trip perf here
}
```

The rail renders nothing unless there are ≥2 seeds and ≥1 result. The
`expansion` summary drives the "How it works" popover's live stat:
`2 queries → RRF → 8 results · TS client (mock)`.

## Files

- `app/lib/recently-viewed.ts` — localStorage history + change event
- `app/components/RecordView.tsx` — records a view on the product page
- `app/lib/hevlayer-client.ts` — TS client stand-in (`searchById` union)
- `app/lib/browsing.ts` — typed `/api/browsing` adapter
- `app/app/api/browsing/route.ts` — drives the client server-side
- `app/components/BrowsingRail.tsx` — homepage rail (client component)
- `app/app/page.tsx` — mounts the rail under the drop band

## Gateway-later path

When the `hevlayer` TypeScript package is available to the storefront build, the swap is contained to
`app/lib/hevlayer-client.ts`:

1. Replace the stand-in import with the real client, constructed from
   `LAYER_GATEWAY_URL` + `LAYER_GATEWAY_API_KEY` (the web pod already holds
   these for `app/lib/layer.ts` namespace warming).
2. Implement `searchById` as: fetch each seed's vector, issue one multi-query
   round trip with a `["vector","ANN", vec]` leg per seed, then fuse the
   parallel `results` with the same RRF already in the stand-in.
3. Surface the real multi-query `layer_perf` in the route response; the "How it
   works" popover gains a `LayerPerfBadge` next to its live stat.
4. The fusion stays client-side (RRF over independent legs is the point of
   choosing multi-query over centroid). `searchById`'s signature does not
   change.

No other file changes: the rail, history, route shape, and adapter are all
written against the array contract, not the mock.
