# hev-shop Claude Context

`hev-shop` is the product-search demo and production storefront for showing how
hevlayer coordinates ingestion, embedding, review search, and tag rollups. This
file is for product, design, research, and strategy context. For engineering
and operations guidance, read `AGENTS.md`.

## Product Role

The storefront demonstrates a concrete buyer workflow over Amazon product data:
search products, inspect product detail, search reviews, and use review-derived
tags as product signals. The interesting hevlayer story is the fan-out shape:
one ingest produces product vectors, review vectors, review classifications,
and aggregate product attributes.

## Design Intent

- Keep the UI useful as a storefront, not just a pipeline demo.
- Make review search and review-derived tags feel like product affordances.
- Treat operational status as supporting evidence for the pipeline story, not
  as the primary user experience.
- Preserve clear seams between storefront UX, indexer API contracts, and Layer
  pipeline mechanics.

## Strategic Notes

- `amazon-products` is the primary product namespace.
- Review embeddings and classifier tags are the differentiating surface.
- The project should continue to prove that Layer pipelines can support
  multiple downstream destinations from one ingest path.
- Product docs should describe what users can do; operational commands belong
  in `AGENTS.md`.
