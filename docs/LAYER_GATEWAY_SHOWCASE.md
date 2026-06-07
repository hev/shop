# Layer Gateway Showcase

`hev-shop` exists to exercise the Layer gateway as an application developer
would use it. The app keeps source-specific logic in workers and leaves vector
storage, cache-aware retrieval, query freshness, and pipeline state management
to Layer. See [hevlayer.com](https://hevlayer.com) for the gateway overview.

## What Layer Adds Over Turbopuffer

Layer's HTTP surface is wire-compatible with turbopuffer for the namespace APIs
hev-shop uses for search and reads. Code points at Layer instead of a
turbopuffer SDK directly, and the app uses `hevlayer.AsyncHevlayer` for gateway
calls.

Layer adds four capabilities on top of that compatible surface, and hev-shop is
structured to make each one visible:

| Capability | Where in hev-shop |
| ---------- | ----------------- |
| **Document cache** — Aerospike pull-through on `fetch_document` / `fetch_many_documents`, populated by warm jobs and read-through. Cache hits show `x-layer-cache: hit`. | Product detail pages call `AsyncHevlayer.fetch_document`; repeated product fetches can be served from the gateway cache. |
| **Snapshots** — field-value snapshots gated on a freshness watermark. | `/meta` materializes a `category` snapshot to drive storefront category facets. |
| **Pipeline state machine** — `pending -> embedding -> indexed/failed` per document, exposed through Layer's pipeline API with atomic claim, leases, heartbeats, and stale-claim recovery. | CPU workers stage product chunks; GPU workers claim pending documents and call `put_pipeline_document_vectors`, which writes vectors and marks docs indexed. KEDA scales workers from `layer_pipeline_stage_count` metrics. |
| **Freshness watermark** — every query response carries `stable_as_of` (epoch ms) and namespaces expose `is_stable`, derived from a consistency watcher that tracks when `unindexed_bytes` reaches 0. | `/search`, `/recommend`, and `/meta` pass the watermark through to the UI. |

These are the properties to keep in mind when adding features: prefer changes
that expose one of them clearly. Avoid adding code that reaches around the
gateway, such as direct turbopuffer writes or private worker-only caches.

## Namespace API

The product index uses the gateway namespace API for reads:

- product vectors are addressed in `amazon-products`
- product search uses `/v2/namespaces/{namespace}/query`
- recommendations use `nearest_to_id`
- product pages fetch cached documents from the gateway
- `/meta` uses namespace metadata and category snapshots

The gateway adds Aerospike pull-through caching and a hidden `_upserted_at`
watermark. The web app passes `stable_as_of` through to the UI so users can see
which consistent snapshot a result set reflects.

Relevant code:

- `hevlayer` SDK (`hev/layer/clients/python`) — `AsyncHevlayer` is the client;
  the indexer imports it directly in `main.py`, `pipeline.py`,
  `extraction.py`, and `worker.py`.
- `search/app/main.py` — query, recommendation, product fetch, and metadata
  endpoints.
- `web/app/api/search/route.ts` and `web/lib/backend.ts` — frontend adapters.

## Pipeline API

The app uses gateway pipeline state instead of maintaining a bespoke GPU queue.
CPU workers stage documents, GPU workers claim and heartbeat documents, and the
gateway owns queue state transitions.

Main stages:

- `pending`: CPU work has staged chunks and metadata.
- `embedding`: a worker has claimed the document lease.
- `indexed`: vectors are written through `put_pipeline_document_vectors`.
- `failed`: the document hit a permanent input error.

Relevant code:

- `indexer/app/extraction.py` — stages product chunks with product metadata and
  image URLs.
- `indexer/app/pipeline.py` — claims pending product docs, fetches image bytes
  in memory, and writes vectors through Layer.
- `indexer/app/worker.py` — `WORKER_TYPE=cpu` or `gpu`.
- `helm/hev-shop/templates/scaledobjects.yaml` — KEDA queries Layer pipeline
  metrics to scale workers.

## Developer Contract

The app should make these gateway properties easy to inspect:

- where chunks are staged before embedding
- which documents are pending, claimed, indexed, or failed
- when turbopuffer is still indexing and which watermark search used
- how worker count follows Layer pipeline state through KEDA
- how product attributes map into turbopuffer's schema

When adding features, prefer examples that expose a gateway behavior directly.
Avoid turning the repo into a general storefront or hiding the gateway behind
too much app-specific abstraction.
