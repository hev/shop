# Reviews Pipeline

> **Status: implemented and in production.** This document is the original
> design plan (PR 1–4 in "Implementation plan" below) and has been preserved
> for the rationale and architectural framing. The "Status" section near the
> end reflects the shipped state. For the current code layout, read
> `indexer/app/pipeline.py` (stages + driver) and `indexer/app/extraction.py`
> (raw ingest). The file references in the per-PR notes below predate the
> consolidation — see the module map in `AGENTS.md` for the current files.

Plan for adding product reviews to hev-shop. Designed to showcase hev layer's parallel fan-out pipelines: one review ingest produces a searchable review index, a per-review LLM classifier, and a tag rollup written back to the product index — all coordinated through the same job-queue primitives as the existing product pipeline.

## Motivation

Reviews give hev-shop a second searchable surface (per-product review search) and feed classifier signal back into product search (filterable tags like "Value Leader", "Falls apart fast"). The architecturally interesting part is the **shape**: a single ingest fans out to three downstream stages writing to three different destinations, with the third stage triggered by debounced upserts from the second. That's a story you cannot tell cleanly with a single-pipeline system.

## Architecture

```
                     ┌──────────────────────────────────────┐
                     │  HF dataset (Amazon-Reviews-2023)    │
                     │  raw_review_{Category} splits        │
                     └──────────────────┬───────────────────┘
                                        │
                                        ▼
                     ┌──────────────────────────────────────┐
                     │  CPU worker: review extraction       │
                     │  Stages each review as a document    │
                     │  to `hev-shop-reviews` pipeline      │
                     └──────────┬───────────────┬───────────┘
                                │               │
              ┌─────────────────┘               └─────────────────┐
              ▼                                                   ▼
  ┌────────────────────────────┐                  ┌──────────────────────────────┐
  │  GPU worker: review-embed  │                  │  CPU worker: review-classify │
  │  Qwen3-Embedding-8B        │                  │  Gemini 2.0 Flash Lite       │
  │  Naive 256-tok chunking    │                  │  via OpenRouter              │
  │  → amazon-reviews-{shard}  │                  │  → review vector tag attrs   │
  │    Turbopuffer namespace   │                  │  + debounced trigger row     │
  └────────────────────────────┘                  └──────────────┬───────────────┘
                                                                 │
                                                                 ▼
                                            ┌──────────────────────────────────┐
                                            │  CPU worker: review-aggregate    │
                                            │  List/fetch tags per asin        │
                                            │  Threshold, pick samples         │
                                            │  → product attrs in              │
                                            │    amazon-products namespace     │
                                            └──────────────────────────────────┘
```

All three downstream workers use the same `FOR UPDATE SKIP LOCKED` pattern as the existing CPU/GPU workers. No external cron, no out-of-band coordination — the aggregator is just another pipeline-stage worker, triggered by the classifier debouncing upserts onto `pipeline_documents`.

## Sharding

**Reviews vector index:** hash-shard into a bounded set of Turbopuffer namespaces. `namespace_for(asin) = amazon-reviews-{hash(asin) % N}` (N=16 initial, doubles cleanly). All review search queries filter by `asin` at Turbopuffer query time so co-location within a shard is preserved.

Why not namespace-per-product: cardinality explosion and per-namespace overhead. Why not namespace-per-category: categories drift and rebalance is painful — hash sharding lets us go N→2N without touching the taxonomy.

**Aerospike side:** shard into sets (Aerospike namespaces are fixed-config, sets are cheap).

## Models

| Stage | Model | Rationale |
|---|---|---|
| Embedding | Qwen3-Embedding-8B (HF: `Qwen/Qwen3-Embedding-8B`) | Open weights, 4096-dim, 32K context. Recall headroom on long-tail product vocabulary. GPU cost absorbed by autoscaler. |
| Classifier | Gemini 2.0 Flash Lite via OpenRouter (~$0.075/M input) | Handles concession structure ("Good but...") that pure cost-floor models (1-3B) miss. Model id is configurable — easy to swap if quality regresses. |

## Chunking

- **Classifier path:** no chunking. One review = one (or batched) classifier call. The LLM reads raw text.
- **Search path:** naive fixed-window — 256 tokens with 32-token overlap using Qwen's tokenizer. The 8B model's representational headroom absorbs sloppy boundaries. Do **not** embed whole reviews as single vectors — single-vector-per-review tanks recall on specific aspects (battery, fit, etc.).

## Tag schema (Phase 1)

11 tags across five axes, all derivable from review text alone:

- **Quality:** Buy it for life, no regrets · Falls apart fast
- **Value:** Value Leader · Overpriced · Worth the splurge
- **Experience:** Good but... · Setup nightmare · Wish I'd bought sooner
- **Reality vs. marketing:** Better in person · Photos misleading
- **Audience fit:** Beginner friendly

Inverse pairs (Buy it for life ↔ Falls apart fast; Value Leader ↔ Overpriced) are intentional — filters work both positively and negatively.

**Storage on the product record (in `amazon-products` namespace):**
- `tags: [str]` — filterable string array. New tags don't require schema migration.
- `tag_counts: {tag: int}` — returnable, for UI signal-strength display.
- `tag_samples: {tag: [review_id]}` — returnable, 2-3 highest-confidence review_ids per tag for UI quoting.

**Per-product cap:** 200 most-recent + 200 most-helpful = 400 max reviews/product classified. Caps OpenRouter spend predictably. Configurable for full-pull mode later.

### Dropped from Phase 1

- **Frequently returned** / **Frequently repurchased** — these are *transaction* signals, not review-text signals. hev-shop dataset is products + reviews only (no order/return data). Inferring from rare phrasings like "had to send it back" appears in ~5% of actual returns; the resulting tag would be noisy and undercount badly. Re-add later if transaction data is ingested, as a separate non-LLM aggregation pipeline.

### Phase 2 (deferred)

- **Buy this instead** — structurally different (relation, not unary tag). Needs NER on review text + catalog resolver to link mentioned products + confidence threshold. Own pipeline stage. Punted to keep Phase 1 scope tight.

## Data model additions

```python
class ReviewRecord:
    asin: str
    review_id: str
    category: str
    rating: int
    title: str | None
    text: str
    helpful_vote: int
    verified_purchase: bool
    timestamp: datetime
```

Classification results live on the first review-vector chunk as Turbopuffer
attributes (`tags`, `tag_confidences`, `review_classified_at`). Aggregation
derives product-level tags by listing and fetching review documents for an ASIN, so
there is no hev-shop-owned table in the gateway database.

## Implementation plan

Four PRs, each shippable on its own.

### PR 1 — Foundation refactor (no behavior change)

The indexer currently hardcodes `default_pipeline_id` in `EmbeddingWorker` and treats `namespace` as a single global config value. Both need parametrization.

- `EmbeddingWorker.__init__` takes `pipeline_id` and `namespace_resolver` instead of reading config defaults
- Add `namespace_for(asin, kind)` resolver: `amazon-products` for products, `amazon-reviews-{hash(asin) % N}` for reviews
- New `PipelineConfig` dataclass (pipeline_id, namespace_resolver, vector_attrs, embedder_type)
- ConfigMap gains `REVIEWS_NAMESPACE_SHARD_COUNT`, `REVIEWS_PIPELINE_ID`
- **Touches:** `config.py`, `embedding.py`, `worker.py`, `vector_attrs.py`, `configmap.yaml`. Product pipeline unchanged.

### PR 2 — Reviews ingest + searchable reviews index

End-to-end vertical for the search path.

- Add `ReviewRecord` model
- Extend `dataset.py` to load `raw_review_{Category}` HF splits; verify these exist on first run
- CPU worker, after staging a product, stages that product's reviews as documents to a new `hev-shop-reviews` layer pipeline
- New GPU worker type `review-embed`: loads Qwen3-Embedding-8B, chunks each review (256-tok windows, 32 overlap), embeds, upserts to `amazon-reviews-{shard}` namespace
- Reviews namespace attrs: filterable `{asin, category, rating}`; returnable `{review_id, chunk_idx, text_chunk}`
- New API `GET /search/reviews?q=&asin=&category=` — resolves shard from asin, applies asin filter at query time
- K8s: new GPU deployment + scaledobject (Qwen3-8B fp16 ≈ 16GB VRAM, same GPU class as CLIP)
- **Risk:** Qwen3-8B cold start ~30s. Keep min replicas ≥1 or accept first-query latency.

### PR 3 — Classifier path + tags on products

End-to-end vertical for the tags path. Runs in parallel to PR 2's embed worker on the same reviews pipeline.

- New CPU worker `review-classify`: claims documents from reviews pipeline, batches 5-10 reviews per OpenRouter call with structured-output prompt for the 11-tag schema, patches tags onto the review vector row, and upserts a debounced aggregate work item through the Layer pipeline API.
- OpenRouter client: model id configurable, API key from k8s secret, retry/backoff
- New CPU worker `review-aggregate`: claims asin jobs, lists IDs in the ASIN's review shard and fetches those documents (threshold `count ≥ max(3, 5% of reviews)`), picks 2-3 highest-confidence samples per tag, upserts product attrs in `amazon-products` namespace
- `/search` accepts `tags` filter param
- **Risk:** OpenRouter spend. Per-product cap (400) is the primary control; any future global spend cap needs an app-owned control-plane service, not direct writes to the gateway database.

### PR 4 — UI surfacing

- Reviews panel on PDP
- Tag chips on product cards
- Tag filter facets in search results
- Tooltip showing sample review snippets per tag
- **Touches:** `web/` only

### Backfill

When PR 2 ships, run a one-time backfill that re-extracts reviews for all already-indexed products. Newly-indexed products get reviews automatically going forward.

## Status

Implemented in this branch:

- Product extraction now also stages capped review work items into the shared
  `hev-shop-reviews` pipeline.
- Review search embeds tokenizer chunks with Qwen and writes them to
  `amazon-reviews-{hash(asin) % N}` shards.
- Review classification uses OpenRouter structured output for the Phase 1 tag
  schema, patches tags onto review-vector attributes, and debounces per-ASIN
  aggregate jobs through the Layer pipeline API.
- Aggregation rolls tag counts/samples back onto product attributes in the
  `amazon-products` namespace.
- The API exposes product tag filters, per-product review search, product fetch,
  and review sample lookup. The web app surfaces tags, tag filters, and review
  chunks.
- Kubernetes manifests include dedicated `review-embed`, `review-classify`, and
  `review-aggregate` workers plus KEDA scalers.

Backfill is still gated on `OPENROUTER_API_KEY`. Fill
`kubernetes/secret.yaml` or the deployed secret before enabling
`review-classify` workers for a full historical run.

Implementation note: the current layer pipeline table has one stage per
`(pipeline_id, document_id)`, so fan-out uses two work-item document IDs per
review (`review-embed:{review_id}` and `review-classify:{review_id}`) in the
same `hev-shop-reviews` pipeline. This preserves independent `FOR UPDATE SKIP
LOCKED` queues without changing layer-gateway schema.
