# hev-shop Claude Context

`hev-shop` is the product-search demo and production storefront for showing how
hev layer coordinates ingestion, product image embedding, product search,
recommendations, and freshness-aware reads. This file is for product, design,
research, and strategy context. For engineering and operations guidance, read
`AGENTS.md`.

## Product Role

The storefront demonstrates a concrete buyer workflow over Amazon product data:
search products, inspect product detail, and browse visually similar products.
The interesting hev layer story is the clean pipeline lifecycle: product
metadata is staged as chunks, GPU workers claim pending docs, CLIP vectors are
written through Layer, and reads expose gateway perf/freshness signals.

## Design Intent

- Keep the UI useful as a storefront, not just a pipeline demo.
- Make visual similarity and semantic product search feel like product
  affordances.
- Treat operational status as supporting evidence for the pipeline story, not
  as the primary user experience.
- Preserve clear boundaries between storefront UX, indexer API contracts, and
  Layer pipeline mechanics.

## Strategic Notes

- `amazon-products` is the primary product namespace.
- CLIP image embeddings are the differentiating retrieval surface.
- The project should prove that Layer pipelines can support a simple,
  production-shaped extraction/embedding loop without an app-owned vector
  bookkeeping layer.
- Product docs should describe what users can do; operational commands belong
  in `AGENTS.md`.

## Pipeline Authoring

hev layer supports two equal authoring surfaces for pipelines: declarative
config (CRD/YAML) and SDK calls in app code. Shop uses both, split by what
each surface owns:

- Worker shape (image, compute pool, scaling) is declarative: the `Pipeline`
  resources under `indexer/pipelines/` are reconciled by the Layer operator,
  which owns the worker Deployments and KEDA scaling.
- Queue creation and the document lifecycle stay in SDK calls
  (`ensure_pipeline` in `indexer/app.py`, chunk/claim/vector calls in the
  stage scripts), because gateway state lives next to the code that uses it.

The SDK and YAML surfaces should round-trip through one schema. Drift between
what the SDK can express and what YAML can express is a Layer bug, not a shop
choice to work around.

App-owned Pipeline/UDF YAML lives under `indexer/pipelines/`. The Helm chart
owns the always-on API/web Deployments and their config injection, not Layer
pipeline shape.
