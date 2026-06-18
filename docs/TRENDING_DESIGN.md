# Trending — splitting "recent searches" into personal + aggregate

Design + build plan for RFC 0040 as it lands in hev-shop. The storefront's
single "recent searches" surface conflated two different reads; this splits them
and makes the aggregate one a real Layer capability.

Upstream RFC: `../layer/docs/rfcs/0040-trending-searches-reduce-udfs.md`.

## The split

| | Your recent searches | Trending |
| --- | --- | --- |
| Scope | this browser | everyone, aggregated |
| Order | recency | volume × result quality (NDCG) |
| Backing | client localStorage | a Layer **reduce UDF** → `amazon-products-trending` |
| Home | header search-bar dropdown | homepage section |
| Explainer | none (a UX nicety, not a capability) | `trending` (search-history + reduce UDF) |

Personal recent is client-only and mirrors the existing
`recently-viewed.ts` + `RecordView` pattern that already powers the browsing
rail. Trending is the showcase: it joins `search-history` (what was asked + the
served ids) with `clickstream` (what was then clicked), scores ranking quality,
and serves a fresh, consistent read — none of which a plain `ORDER BY ts DESC`
can do.

## What it showcases

The first inhabitant of `indexer/udfs/`. Pipelines demonstrate compute *during*
ingestion; this demonstrates a **reduce UDF** — compute *over* operational data
already in Layer — materialized as a derived namespace the web reads in one
O(1), freshness-stamped query.

## Scoring (RFC 0040 §5)

Per normalized query `q`, over the window:

```
count(q) = number of searches with that normalized query
ndcg(q)  = mean NDCG over those searches (Phase 2; 0 in Phase 1)
score(q) = count(q) * (1 + W * ndcg(q))
```

`W` = `TrendingConfig.quality_weight` (`TRENDING_QUALITY_WEIGHT`). Phase 1 sets
`W = 0` (pure volume); Phase 2 turns it up. A `min_count` floor keeps a single
rare query from surfacing verbatim.

The scoring is pure and lives in `common/hev_shop_common/trending.py` so it is
unit-testable without a gateway and reusable by future reduces. The worker owns
only I/O.

## Phases

- **Phase 0 — storefront only, no Layer dependency. Shippable now.**
  Personal recent searches in localStorage + relabel. Files: `recent-searches-local.ts`,
  `RecordSearch.tsx`; `SearchBar` reads them. The old server-backed personal
  recent-search mock is retired.
- **Phase 1 — frequency trending.** `W = 0`. The reduce reads `search-history`
  only, no click attribution. Runs as a Layer Function with
  `triggers: [schedule]`.
  Files: `indexer/trending.py`, `udfs/trending.yaml`, the `/search/trending`
  read, `trending.ts` + `Trending.tsx`, the `trending` explainer entry.
- **Phase 2 — NDCG trending.** `W > 0`. Adds the `clickstream` read + click
  attribution: thread the search `traceparent` from result link → product page →
  `/product/{asin}` fetch. The gateway side is already done (RFC 0040 §4, gap 3).

## Layer dependency

Phase 1+ uses **`triggers: [schedule]`** on the `Function` CRD/operator: a
reduce is invoked once per tick with no row-level input. The worker logic does
not depend on the scheduler — `run_trending_once` is a pure tick, and `amain`
offers a dev interval loop + `TRENDING_RUN_ONCE=1` for manual runs.

The reads/writes do **not** need a layer change: `list_search_history` /
`list_clickstream` already exist on `AsyncHevlayer`, and the worker upserts the
output namespace itself. (We deliberately did not propose `spec.sources` /
`spec.output` — that would push the document lifecycle into the CRD, against the
CLAUDE.md authoring split.)

## File map

Pure core + worker (Python):
- `common/hev_shop_common/trending.py` — scoring reduce (pure, testable core)
- `common/tests/test_trending.py` — scoring unit tests
- `indexer/trending.py` — reduce worker (reads history, upserts `<ns>-trending`)
- `indexer/tests/test_trending.py` — worker I/O tests
- `indexer/udfs/trending.yaml` — `Function` resource (`triggers: [schedule]`)
- `common/hev_shop_common/config.py` — `trending_*` settings
- `indexer/Dockerfile` — `trending` target (CMD `python trending.py`)

Read API (Python):
- `search/models.py` — `TrendingEntry`, `TrendingResponse`
- `search/app.py` — `GET /search/trending` (reads the materialized namespace)
- `search/tests/test_trending.py` — endpoint tests

Storefront (TypeScript):
- `app/lib/recent-searches-local.ts` — Phase 0 personal recent (localStorage)
- `app/components/RecordSearch.tsx` — Phase 0 records the active query
- `app/lib/backend.ts` — `backendTrending()` adapter
- `app/lib/trending.ts` — `getTrending()` server adapter (mock fallback)
- `app/components/Trending.tsx` — homepage Trending section
- `app/lib/feature-explainers.ts` — `trending` registry entry
- `app/app/page.tsx` — mounts `<Trending />` under the hero
- `app/components/SearchBar.tsx` — reads `recent-searches-local` for the dropdown

## Response contract (`GET /search/trending`)

```jsonc
// GET /search/trending?limit=12
{
  "namespace": "amazon-products-trending",
  "mode": "frequency",          // "frequency" (Phase 1) | "quality" (Phase 2)
  "entries": [
    { "query": "wireless headphones", "count": 41, "score": 41.0,
      "ndcg": 0.0, "sample_top_ids": ["B0001", "B0002"] }
  ],
  "stable_as_of": 1733760000000,
  "layer_perf": { "latency_ms": 3, "cache_status": null }
}
```

The `trending` explainer's live stat reads off `mode` ("by volume" vs "by volume
× result quality"), so the UI never claims a quality signal it isn't computing.
