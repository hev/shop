"""Consolidated view of the layer N-stage pipeline.

Each stage of the DAG is one entry in STAGES; the driver `run_stage`
owns the claim / heartbeat / release lifecycle so each `process_*`
function only contains the work that's unique to that stage.

Stages, top-down:

    extract:          (postgres job queue) → stages products + raw reviews
                                             into the layer pipelines
    embed-products:   pending  → indexed   (CLIP image vectors, prod ns)
    embed-reviews:    pending  → indexed   (Qwen text vectors, review ns,
                                            chunked, prefix=embed:)
    classify-reviews: pending  → indexed   (OpenRouter tag classification,
                                            prefix=classify:) — fans out
                                            ASINs into the aggregate pipeline
    aggregate-tags:   pending  → indexed   (Postgres rollup → PATCH product
                                            rows with tag_counts/samples)
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import Settings, get_settings
from .database import Database
from .layer_client import LayerClient
from datetime import datetime, timezone

from .classifier import ReviewClassificationInput
from .records import (
    REVIEW_CLASSIFY_PREFIX,
    REVIEW_EMBED_PREFIX,
    product_vector_attributes,
    review_namespace_for,
    review_vector_attributes,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Driver — one copy of claim/heartbeat/release for every stage
# ---------------------------------------------------------------------------


@dataclass
class StageContext:
    settings: Settings
    database: Database
    layer: LayerClient
    # Lazy singletons so stages that need a model don't pay for one they don't.
    _clip_image: Any = None
    _clip_text: Any = None
    _qwen: Any = None
    _classifier: Any = None


@dataclass(frozen=True)
class StageOutcome:
    """Per-document disposition after process() runs."""
    complete: list[str] = field(default_factory=list)  # → indexed
    fail:     list[str] = field(default_factory=list)  # → failed (poison)
    release:  list[str] = field(default_factory=list)  # → pending (retry)


@dataclass(frozen=True)
class Stage:
    name: str
    pipeline_attr: str           # Settings field that holds the pipeline id
    from_stage: str              # the stage to claim from / transition out of
    claim_size_attr: str         # Settings field controlling claim batch size
    prefix: str | None = None    # document_id_prefix filter, if any
    process: Callable[[StageContext, list[str]], Awaitable[StageOutcome]] = None  # type: ignore
    setup:   Callable[[StageContext], Awaitable[None]] | None = None


async def run_stage(stage: Stage, ctx: StageContext, stop: asyncio.Event) -> None:
    if stage.setup:
        await stage.setup(ctx)
    while not stop.is_set():
        n = await _run_once(stage, ctx)
        if n == 0:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), ctx.settings.worker_poll_seconds)


async def _run_once(stage: Stage, ctx: StageContext) -> int:
    pipeline_id = getattr(ctx.settings, stage.pipeline_attr)
    claim_size = getattr(ctx.settings, stage.claim_size_attr)
    worker_id = ctx.settings.resolved_worker_id

    doc_ids = await ctx.layer.claim_pipeline_documents(
        pipeline_id,
        limit=claim_size,
        worker_id=worker_id,
        lease_seconds=ctx.settings.claim_lease_seconds,
        claim_stage=stage.from_stage,
        document_id_prefix=stage.prefix,
    )
    if not doc_ids:
        return 0

    active = set(doc_ids)
    hb = asyncio.create_task(_heartbeat(ctx, pipeline_id, stage.from_stage, active))
    try:
        outcome = await stage.process(ctx, doc_ids)
    except BaseException:
        if active:
            await ctx.layer.release_pipeline_documents(
                pipeline_id, sorted(active),
                from_stage=stage.from_stage, worker_id=worker_id,
            )
        raise
    finally:
        hb.cancel()
        with suppress(asyncio.CancelledError):
            await hb

    if outcome.complete:
        await ctx.layer.complete_pipeline_documents(
            pipeline_id, outcome.complete, from_stage=stage.from_stage, worker_id=worker_id,
        )
    if outcome.fail:
        await ctx.layer.fail_pipeline_documents(
            pipeline_id, outcome.fail, from_stage=stage.from_stage, worker_id=worker_id,
        )
    if outcome.release:
        await ctx.layer.release_pipeline_documents(
            pipeline_id, outcome.release, from_stage=stage.from_stage, worker_id=worker_id,
        )
    return len(outcome.complete)


async def _heartbeat(ctx: StageContext, pipeline_id: str, stage: str, active: set[str]) -> None:
    while True:
        await asyncio.sleep(ctx.settings.claim_heartbeat_seconds)
        if active:
            await ctx.layer.heartbeat_pipeline_documents(
                pipeline_id, sorted(active),
                stage=stage, worker_id=ctx.settings.resolved_worker_id,
            )


# ---------------------------------------------------------------------------
# Stage: embed-products  (CLIP image → product namespace)
# Showing one stage fully fleshed out so you can see how much smaller a
# stage gets when the lifecycle is gone. The remaining stages are stubs
# whose bodies lift from the existing worker classes.
# ---------------------------------------------------------------------------


async def setup_embed_products(ctx: StageContext) -> None:
    await ctx.layer.create_pipeline(
        ctx.settings.default_pipeline_id,
        ctx.settings.namespace,
        ctx.settings.distance_metric,
    )


async def process_embed_products(ctx: StageContext, doc_ids: list[str]) -> StageOutcome:
    fail: list[str] = []
    prepared: list[tuple[str, Path, dict[str, Any]]] = []  # (doc_id, image, attrs)

    for doc_id in doc_ids:
        chunks = await ctx.layer.get_chunks(ctx.settings.default_pipeline_id, doc_id)
        if not chunks:
            fail.append(doc_id)
            continue
        meta = chunks[0].get("metadata") or {}
        image = Path(meta.get("image_path", ""))
        if not image.is_file():
            fail.append(doc_id)
            continue
        attrs = product_vector_attributes(meta, doc_id)
        attrs.update(await ctx.database.aggregate_review_tag_attrs(
            str(attrs["asin"]),
            min_count=ctx.settings.review_tag_min_count,
            min_fraction=ctx.settings.review_tag_min_fraction,
            sample_count=ctx.settings.review_tag_sample_count,
        ))
        prepared.append((doc_id, image, attrs))

    if not prepared:
        return StageOutcome(fail=fail)

    embedder = _clip_image(ctx)
    complete: list[str] = []
    release: list[str] = []
    batch = ctx.settings.embedding_batch_size
    for i in range(0, len(prepared), batch):
        window = prepared[i : i + batch]
        try:
            vectors = await asyncio.to_thread(
                embedder.encode_image_paths, [item[1] for item in window]
            )
        except Exception:
            logger.exception("CLIP batch failed")
            release.extend(item[0] for item in window)
            continue
        upserts = [
            {"id": doc_id, "vector": v, "attributes": attrs}
            for (doc_id, _img, attrs), v in zip(window, vectors, strict=True)
        ]
        await ctx.layer.upsert_vectors(ctx.settings.namespace, upserts)
        complete.extend(item[0] for item in window)

    return StageOutcome(complete=complete, fail=fail, release=release)


# ---------------------------------------------------------------------------
# Stage: embed-reviews  (Qwen chunked text → review namespace)
# ---------------------------------------------------------------------------

async def process_embed_reviews(ctx: StageContext, doc_ids: list[str]) -> StageOutcome:
    embedder = _qwen(ctx)
    fail: list[str] = []
    release: list[str] = []
    complete: list[str] = []

    # (doc_id, namespace, [{"id": vector_id, "attributes": attrs, "text_chunk": str}, ...])
    prepared: list[tuple[str, str, list[dict[str, Any]]]] = []
    for doc_id in doc_ids:
        try:
            chunks = await ctx.layer.get_chunks(ctx.settings.reviews_pipeline_id, doc_id)
        except Exception:
            logger.exception("failed to prepare review document", extra={"doc_id": doc_id})
            release.append(doc_id)
            continue
        if not chunks:
            fail.append(doc_id)
            continue
        raw = chunks[0]
        metadata = raw.get("metadata") or {}
        text = raw.get("text") or ""
        asin = str(metadata.get("asin") or "")
        review_id = str(metadata.get("review_id") or doc_id)
        if not asin or not text.strip():
            fail.append(doc_id)
            continue
        text_chunks = embedder.chunk_text(
            text,
            chunk_tokens=ctx.settings.review_chunk_tokens,
            chunk_overlap=ctx.settings.review_chunk_overlap,
        )
        if not text_chunks:
            fail.append(doc_id)
            continue
        namespace = review_namespace_for(
            asin,
            namespace_base=ctx.settings.reviews_namespace_base,
            shard_count=ctx.settings.reviews_namespace_shard_count,
        )
        vector_items = [
            {
                "id": f"{review_id}:chunk:{idx:04d}",
                "attributes": review_vector_attributes(
                    metadata, doc_id, chunk_idx=idx, text_chunk=chunk_text,
                ),
            }
            for idx, chunk_text in enumerate(text_chunks)
        ]
        prepared.append((doc_id, namespace, vector_items))

    if not prepared:
        return StageOutcome(fail=fail, release=release)

    # Batch-encode across all (doc_id, vector_id, item) flat tuples, then
    # upsert per-doc so a single doc fully succeeds or fully releases.
    flat: list[tuple[str, dict[str, Any]]] = [
        (doc_id, item) for doc_id, _ns, items in prepared for item in items
    ]
    batch_size = ctx.settings.review_embedding_batch_size
    for batch in _batches(flat, batch_size):
        texts = [str(item[1]["attributes"]["text_chunk"]) for item in batch]
        try:
            vectors = embedder.encode_texts(texts)
        except Exception:
            logger.exception("Qwen review embedding batch failed")
            batch_doc_ids = sorted({doc_id for doc_id, _item in batch})
            for doc_id in batch_doc_ids:
                if doc_id not in release:
                    release.append(doc_id)
            continue
        for (_doc_id, item), vector in zip(batch, vectors, strict=True):
            item["vector"] = vector

    for doc_id, namespace, items in prepared:
        if doc_id in release:
            continue
        if any("vector" not in item for item in items):
            continue
        try:
            await ctx.layer.upsert_vectors(namespace, items)
            complete.append(doc_id)
        except Exception:
            logger.exception("failed to upsert review vector batch")
            release.append(doc_id)

    return StageOutcome(complete=complete, fail=fail, release=release)


# ---------------------------------------------------------------------------
# Stage: classify-reviews  (OpenRouter tag classify → enqueue aggregate)
# ---------------------------------------------------------------------------

async def setup_classify_reviews(ctx: StageContext) -> None:
    await ctx.layer.create_pipeline(
        ctx.settings.reviews_pipeline_id,
        ctx.settings.reviews_namespace_base,
        ctx.settings.distance_metric,
    )
    await ctx.layer.create_pipeline(
        ctx.settings.review_aggregate_pipeline_id,
        ctx.settings.namespace,
        ctx.settings.distance_metric,
    )


async def process_classify_reviews(ctx: StageContext, doc_ids: list[str]) -> StageOutcome:
    # Behavior shift from the old worker: we claim then release when the
    # API key is missing (the old worker short-circuited before claiming).
    # End state is identical — no progress, no tag writes — at the cost
    # of one extra lease round-trip per idle tick.
    if not ctx.settings.openrouter_api_key:
        logger.warning("OPENROUTER_API_KEY is not set; releasing claimed review docs")
        return StageOutcome(release=list(doc_ids))

    if not await ctx.database.try_reserve_review_classification(
        usage_date=datetime.now(timezone.utc).date(),
        review_count=len(doc_ids),
        daily_review_limit=ctx.settings.review_classification_daily_review_limit,
    ):
        logger.warning("daily review classification cap reached")
        return StageOutcome(release=list(doc_ids))

    fail: list[str] = []
    release: list[str] = []
    reviews: list[ReviewClassificationInput] = []
    doc_id_by_review: dict[str, str] = {}

    for doc_id in doc_ids:
        try:
            chunks = await ctx.layer.get_chunks(
                ctx.settings.reviews_pipeline_id, doc_id
            )
        except Exception:
            logger.exception(
                "failed to prepare review classification", extra={"doc_id": doc_id}
            )
            release.append(doc_id)
            continue
        if not chunks:
            fail.append(doc_id)
            continue
        chunk = chunks[0]
        metadata = chunk.get("metadata") or {}
        text = str(chunk.get("text") or "").strip()
        asin = str(metadata.get("asin") or "")
        review_id = str(metadata.get("review_id") or "")
        if not asin or not review_id or not text:
            fail.append(doc_id)
            continue
        doc_id_by_review[review_id] = doc_id
        reviews.append(
            ReviewClassificationInput(
                asin=asin,
                review_id=review_id,
                rating=metadata.get("rating"),
                title=metadata.get("title"),
                text=text,
            )
        )

    if not reviews:
        return StageOutcome(fail=fail, release=release)

    try:
        classified = await _classifier(ctx).classify(reviews)
    except Exception:
        logger.exception("review classifier request failed")
        # Release everything we were about to classify; the docs we already
        # marked fail (missing fields) stay failed.
        release.extend(doc_id_by_review[review.review_id] for review in reviews)
        return StageOutcome(fail=fail, release=release)

    complete: list[str] = []
    aggregate_asins: list[str] = []
    for review in reviews:
        tags = classified.get(review.review_id, [])
        await ctx.database.replace_review_classification(
            asin=review.asin,
            review_id=review.review_id,
            tags=[(tag.tag, tag.confidence) for tag in tags],
        )
        aggregate_asins.append(review.asin)
        complete.append(doc_id_by_review[review.review_id])

    # The cross-stage hand-off: transition the touched ASINs to `pending`
    # on the aggregate pipeline so the next-stage worker can pick them up.
    await ctx.layer.set_pipeline_documents_stage(
        ctx.settings.review_aggregate_pipeline_id,
        sorted(set(aggregate_asins)),
        stage="pending",
        create_missing=True,
    )

    logger.info("classified %s reviews", len(reviews))
    return StageOutcome(complete=complete, fail=fail, release=release)


# ---------------------------------------------------------------------------
# Stage: aggregate-tags  (postgres rollup → PATCH product rows)
# ---------------------------------------------------------------------------

async def setup_aggregate_tags(ctx: StageContext) -> None:
    await ctx.layer.create_pipeline(
        ctx.settings.review_aggregate_pipeline_id,
        ctx.settings.namespace,
        ctx.settings.distance_metric,
    )


async def process_aggregate_tags(ctx: StageContext, asins: list[str]) -> StageOutcome:
    # `asins` are the claimed doc_ids — the aggregate pipeline indexes
    # rows by ASIN, so the driver abstraction doesn't notice the rename.
    patches: list[dict[str, Any]] = []
    for asin in asins:
        attrs = await ctx.database.aggregate_review_tag_attrs(
            asin,
            min_count=ctx.settings.review_tag_min_count,
            min_fraction=ctx.settings.review_tag_min_fraction,
            sample_count=ctx.settings.review_tag_sample_count,
        )
        patches.append({"id": asin, "attributes": attrs})

    try:
        await ctx.layer.patch_attributes(ctx.settings.namespace, patches)
    except Exception:
        logger.exception("failed to aggregate review tags")
        return StageOutcome(release=list(asins))

    return StageOutcome(complete=list(asins))


# ---------------------------------------------------------------------------
# Stage manifest — the layer N-stage pipeline at a glance
# ---------------------------------------------------------------------------

STAGES: dict[str, Stage] = {
    "embed-products": Stage(
        name="embed-products",
        pipeline_attr="default_pipeline_id",
        from_stage="embedding",
        claim_size_attr="embedding_claim_size",
        setup=setup_embed_products,
        process=process_embed_products,
    ),
    "embed-reviews": Stage(
        name="embed-reviews",
        pipeline_attr="reviews_pipeline_id",
        from_stage="embedding",
        claim_size_attr="embedding_claim_size",
        prefix=REVIEW_EMBED_PREFIX,
        process=process_embed_reviews,
    ),
    "classify-reviews": Stage(
        name="classify-reviews",
        pipeline_attr="reviews_pipeline_id",
        from_stage="classifying",
        claim_size_attr="review_classification_batch_size",
        prefix=REVIEW_CLASSIFY_PREFIX,
        setup=setup_classify_reviews,
        process=process_classify_reviews,
    ),
    "aggregate-tags": Stage(
        name="aggregate-tags",
        pipeline_attr="review_aggregate_pipeline_id",
        from_stage="aggregating",
        claim_size_attr="review_aggregate_batch_size",
        setup=setup_aggregate_tags,
        process=process_aggregate_tags,
    ),
    # "extract" stays separate — it pulls from the Postgres job queue, not
    # from a layer stage — and remains in extraction.py (or moves here as a
    # special-cased run_extract(ctx, stop)).
}


# ---------------------------------------------------------------------------
# Lazy embedder/classifier singletons (kept inline so a stage's deps are
# obvious from one read of this file)
# ---------------------------------------------------------------------------

def _clip_image(ctx: StageContext):
    if ctx._clip_image is None:
        from .embedders import CLIPImageEmbedder
        ctx._clip_image = CLIPImageEmbedder(ctx.settings)
    return ctx._clip_image


def _qwen(ctx: StageContext):
    if ctx._qwen is None:
        from .embedders import QwenTextEmbedder
        ctx._qwen = QwenTextEmbedder(ctx.settings)
    return ctx._qwen


def _classifier(ctx: StageContext):
    if ctx._classifier is None:
        from .classifier import OpenRouterReviewClassifier
        ctx._classifier = OpenRouterReviewClassifier(ctx.settings)
    return ctx._classifier


def _batches[T](items: list[T], size: int) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# ---------------------------------------------------------------------------
# Entrypoint — replaces worker.py's WORKER_TYPE switch
#   python -m indexer.app.pipeline embed-products
# ---------------------------------------------------------------------------

async def amain(stage_name: str) -> None:
    logging.basicConfig(level=logging.INFO)
    if stage_name not in STAGES:
        raise SystemExit(f"unknown stage {stage_name!r}; choose from {sorted(STAGES)}")
    settings = get_settings()
    database = await Database.connect(settings.layer_database_url)
    await database.ensure_schema()
    layer = LayerClient(settings.layer_gateway_url, settings.http_timeout_seconds)
    ctx = StageContext(settings=settings, database=database, layer=layer)
    stop = asyncio.Event()
    _install_signals(stop)
    try:
        await run_stage(STAGES[stage_name], ctx, stop)
    finally:
        await layer.close()
        await database.close()


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


if __name__ == "__main__":
    import sys
    asyncio.run(amain(sys.argv[1] if len(sys.argv) > 1 else ""))
