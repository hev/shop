# Layer Gateway Showcase

`hev-shop` exists to exercise the Layer gateway as an application developer
would use it. The app keeps source-specific logic in workers and leaves vector
storage, cache-aware retrieval, query freshness, and pipeline state management
to Layer. See [hevlayer.com](https://hevlayer.com) for the gateway overview.

## Namespace API

The product index uses the gateway namespace API as its only Turbopuffer write
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
- `indexer/app/embedding.py`
- `indexer/app/review_workers.py`
- `web/app/api/search/route.ts`

## Pipeline API

The app uses gateway pipeline state instead of maintaining a bespoke GPU queue.
CPU workers stage documents, GPU workers claim and heartbeat documents, and the
gateway owns the PostgreSQL state transitions.

Main stages:

- `pending`: CPU work has staged chunks and metadata
- `embedding`: a worker has claimed the document lease
- `indexed`: vectors are in Turbopuffer
- `failed`: the document exceeded retry policy or hit a permanent error

The review pipeline deliberately fans out from one ingest into multiple work
items. That makes the gateway's claim and stage APIs visible under a realistic
parallel workload.

Relevant code:

- `indexer/app/extraction.py`
- `indexer/app/worker.py`
- `indexer/app/review_workers.py`
- `kubernetes/*-scaledobject.yaml`

## Developer Contract

The app should make these gateway properties easy to inspect:

- where chunks are staged before embedding
- which documents are pending, claimed, indexed, or failed
- when Turbopuffer is still indexing and which watermark search used
- how worker count follows PostgreSQL pipeline state through KEDA
- how product attributes map into Turbopuffer's schema

When adding features, prefer examples that expose a gateway behavior directly.
Avoid turning the repo into a general storefront or hiding the gateway behind
too much app-specific abstraction.
