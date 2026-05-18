# Layer Gateway Showcase

`hev-shop` exists to exercise the Layer gateway as an application developer
would use it. The app keeps source-specific logic in workers and leaves vector
storage, cache-aware retrieval, query freshness, and pipeline state management
to Layer. See [hevlayer.com](https://hevlayer.com) for the gateway overview.

## What Layer adds over turbopuffer

Layer's HTTP surface is wire-compatible with turbopuffer for the namespace
APIs hev-shop uses for search and writes — same paths, same request and
response shapes for `query`, `upserts`, `patch`, `fetch_document`, and the
schema operations. Code that points at Layer instead of turbopuffer keeps
working; nothing in this repo imports a turbopuffer SDK directly. The single
HTTP entrypoint lives in
[`indexer/app/layer_client.py`](../indexer/app/layer_client.py).

Layer adds four capabilities on top of that compatible surface, and hev-shop
is structured to make each one visible:

| Capability | Where in hev-shop |
| ---------- | ----------------- |
| **Document cache** — Aerospike pull-through on `fetch_document` / `fetch_many_documents`, populated by warm scans and read-through. Cache hits show `x-layer-cache: hit`. | Product detail pages call `LayerClient.fetch_document`; the storefront's `/product/[asin]` route reads from the cache without touching turbopuffer for the second hit. |
| **Scans** — `field_values`, full-document, auto-mode source selection (cache vs origin) gated on a freshness watermark, plus a `warm` operation that primes the cache. | `/meta` issues a `field_values` scan on `category` to drive the landing-page facets; the gateway picks cache or origin based on `stable_as_of`. |
| **Pipeline state machine** — `pending → embedding → indexed/failed` per document, exposed through Layer's pipeline API with atomic claim, leases, heartbeats, and stale-claim recovery. | `pipeline.py` is the entire app-side contract: claim, heartbeat, complete/fail/release. KEDA scales workers from `layer_pipeline_stage_count` metrics. |
| **Freshness watermark** — every query response carries `stable_as_of` (epoch ms) and namespaces expose `is_stable`, derived from a consistency watcher that tracks when `unindexed_bytes` reaches 0. | `/search`, `/search/reviews`, and `/meta` pass the watermark through to the UI; the homepage renders "last indexed at …" against it. |

These are the four properties to keep in mind when adding features: prefer
changes that expose one of them more clearly. Avoid adding code that reaches
around the gateway (a direct turbopuffer call, a private worker-only cache,
an out-of-band scheduler) — that defeats the demo.

## Namespace API

The product index uses the gateway namespace API as its only turbopuffer write
path:

- product vectors are upserted into `amazon-products`
- review vectors are written to `amazon-reviews-*` shards
- product search uses `/v2/namespaces/{namespace}/query`
- product pages and similar-item paths can use fetch/query/scan surfaces

The gateway adds Aerospike pull-through caching and a hidden `_upserted_at`
watermark. The web app passes `stable_as_of` through to the UI so users can see
which consistent snapshot a result set reflects.

Relevant code:

- `indexer/app/layer_client.py`
- `indexer/app/pipeline.py` (`process_embed_products`, `process_embed_reviews`,
  `process_aggregate_tags` — namespace upserts and PATCH attribute rollup)
- `web/app/api/search/route.ts`

## Pipeline API

The app uses gateway pipeline state instead of maintaining a bespoke GPU queue.
CPU workers stage documents, GPU workers claim and heartbeat documents, and the
gateway owns the queue state transitions.

Main stages:

- `pending`: CPU work has staged chunks and metadata
- `embedding`: a worker has claimed the document lease
- `indexed`: vectors are in turbopuffer
- `failed`: the document exceeded retry policy or hit a permanent error

The review pipeline deliberately fans out from one ingest into multiple work
items in the shared `hev-shop-reviews` pipeline (one `embed:` doc, one
`classify:` doc per review), with classification debouncing per-ASIN jobs
onto a third `review-aggregate` pipeline. That makes the gateway's claim,
stage, and cross-pipeline transition APIs visible under a realistic parallel
workload.

Relevant code:

- `indexer/app/extraction.py` — stages products and per-review work items
- `indexer/app/pipeline.py` — `STAGES` manifest + `run_stage` driver + each
  stage's `process_*` function
- `indexer/app/worker.py` — `WORKER_TYPE` env → stage dispatch
- `kubernetes/*-scaledobject.yaml`, `helm/hev-shop/templates/scaledobjects.yaml` —
  KEDA queries Layer pipeline metrics to scale each stage

## Developer Contract

The app should make these gateway properties easy to inspect:

- where chunks are staged before embedding
- which documents are pending, claimed, indexed, or failed
- when turbopuffer is still indexing and which watermark search used
- how worker count follows PostgreSQL pipeline state through KEDA
- how product attributes map into turbopuffer's schema

When adding features, prefer examples that expose a gateway behavior directly.
Avoid turning the repo into a general storefront or hiding the gateway behind
too much app-specific abstraction.
