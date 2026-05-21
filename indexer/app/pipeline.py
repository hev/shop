"""Consolidated view of the layer N-stage pipeline.

Each stage of the DAG is one entry in STAGES; the driver `run_stage`
owns the claim / heartbeat / release lifecycle so each `process_*`
function only contains the work that's unique to that stage.

Stages, top-down:

    extract:          (Layer extraction pipeline) → stages products + raw
                                             reviews into the layer pipelines
    embed-products:   pending  → indexed   (CLIP image vectors, prod ns)
    embed-reviews:    pending  → indexed   (Qwen text vectors, review ns,
                                            chunked, prefix=embed:)
    classify-reviews: pending  → indexed   (OpenRouter tag classification,
                                            prefix=classify:) — fans out
                                            ASINs into the aggregate pipeline
    aggregate-tags:   pending  → indexed   (review namespace scan → PATCH
                                            product rows with tag_counts/samples)
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from contextlib import suppress
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
from typing import Any, Awaitable, Callable

from hevlayer import (
    AsyncHevlayer,
    Chunk,
    ClaimDocumentsRequest,
    CreatePipelineRequest,
    CreateScanRequest,
    HeartbeatDocumentsRequest,
    PatchDocument,
    PatchRequest,
    PutChunksRequest,
    SetDocumentsStageRequest,
    UpsertDocument,
    UpsertRequest,
)

from datetime import datetime, timezone

from hev_shop_common.config import Settings, get_settings
from hev_shop_common.records import (
    REVIEW_CLASSIFY_PREFIX,
    REVIEW_EMBED_PREFIX,
    REVIEW_TAGS,
    product_vector_attributes,
    review_raw_chunk_id,
    review_namespace_for,
    review_vector_attributes,
    review_work_document_id,
)

from .classifier import ReviewClassificationInput

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Driver — one copy of claim/heartbeat/release for every stage
# ---------------------------------------------------------------------------


@dataclass
class StageContext:
    settings: Settings
    layer: AsyncHevlayer
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

    claim = await ctx.layer.claim_documents(
        pipeline_id,
        ClaimDocumentsRequest(
            limit=claim_size,
            worker_id=worker_id,
            lease_seconds=ctx.settings.claim_lease_seconds,
            claim_stage=stage.from_stage,
            document_id_prefix=stage.prefix,
        ),
    )
    doc_ids = list(claim.documents)
    if not doc_ids:
        return 0

    active = set(doc_ids)
    hb = asyncio.create_task(_heartbeat(ctx, pipeline_id, stage.from_stage, active))
    try:
        outcome = await stage.process(ctx, doc_ids)
    except BaseException:
        if active:
            await ctx.layer.release_documents(
                pipeline_id, sorted(active),
                from_stage=stage.from_stage, worker_id=worker_id,
            )
        raise
    finally:
        hb.cancel()
        with suppress(asyncio.CancelledError):
            await hb

    accounted = set(outcome.complete) | set(outcome.fail) | set(outcome.release)
    unaccounted = sorted(active - accounted)
    if unaccounted:
        logger.warning(
            "stage returned without a disposition for claimed documents; releasing",
            extra={
                "stage": stage.name,
                "pipeline_id": pipeline_id,
                "unaccounted_count": len(unaccounted),
            },
        )
        outcome = StageOutcome(
            complete=outcome.complete,
            fail=outcome.fail,
            release=[*outcome.release, *unaccounted],
        )

    if outcome.complete:
        await ctx.layer.complete_documents(
            pipeline_id, outcome.complete, from_stage=stage.from_stage, worker_id=worker_id,
        )
    if outcome.fail:
        await ctx.layer.fail_documents(
            pipeline_id, outcome.fail, from_stage=stage.from_stage, worker_id=worker_id,
        )
    if outcome.release:
        await ctx.layer.release_documents(
            pipeline_id, outcome.release, from_stage=stage.from_stage, worker_id=worker_id,
        )
    return len(outcome.complete)


async def _heartbeat(ctx: StageContext, pipeline_id: str, stage: str, active: set[str]) -> None:
    while True:
        await asyncio.sleep(ctx.settings.claim_heartbeat_seconds)
        if active:
            await ctx.layer.heartbeat_documents(
                pipeline_id,
                HeartbeatDocumentsRequest(
                    document_ids=sorted(active),
                    stage=stage,
                    worker_id=ctx.settings.resolved_worker_id,
                ),
            )


# ---------------------------------------------------------------------------
# Stage: embed-products  (CLIP image → product namespace)
# Showing one stage fully fleshed out so you can see how much smaller a
# stage gets when the lifecycle is gone. The remaining stages are stubs
# whose bodies lift from the existing worker classes.
# ---------------------------------------------------------------------------


async def setup_embed_products(ctx: StageContext) -> None:
    await ctx.layer.ensure_pipeline(
        CreatePipelineRequest(
            id=ctx.settings.default_pipeline_id,
            target_namespace=ctx.settings.namespace,
            distance_metric=ctx.settings.distance_metric,
        )
    )
    _clip_image(ctx)


async def process_embed_products(ctx: StageContext, doc_ids: list[str]) -> StageOutcome:
    fail: list[str] = []
    prepared: list[tuple[str, Path, dict[str, Any]]] = []  # (doc_id, image, attrs)

    for doc_id in doc_ids:
        chunks = await ctx.layer.get_pipeline_document_chunks(
            ctx.settings.default_pipeline_id, doc_id
        )
        if not chunks:
            fail.append(doc_id)
            continue
        meta = chunks[0].metadata or {}
        image = Path(meta.get("image_path", ""))
        if not image.is_file():
            fail.append(doc_id)
            continue
        attrs = product_vector_attributes(meta, doc_id)
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
            UpsertDocument(id=doc_id, vector=v, attributes=attrs)
            for (doc_id, _img, attrs), v in zip(window, vectors, strict=True)
        ]
        await ctx.layer.upsert_documents(
            ctx.settings.namespace, UpsertRequest(upserts=upserts)
        )
        complete.extend(item[0] for item in window)

    return StageOutcome(complete=complete, fail=fail, release=release)


# ---------------------------------------------------------------------------
# Stage: embed-reviews  (Qwen chunked text → review namespace)
# ---------------------------------------------------------------------------

async def setup_embed_reviews(ctx: StageContext) -> None:
    await ctx.layer.ensure_pipeline(
        CreatePipelineRequest(
            id=ctx.settings.reviews_pipeline_id,
            target_namespace=ctx.settings.reviews_namespace_base,
            distance_metric=ctx.settings.distance_metric,
        )
    )
    _qwen(ctx)


async def process_embed_reviews(ctx: StageContext, doc_ids: list[str]) -> StageOutcome:
    embedder = _qwen(ctx)
    fail: list[str] = []
    release: list[str] = []
    complete: list[str] = []

    # (doc_id, namespace, vector items, optional classify handoff chunk)
    prepared: list[
        tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]
    ] = []
    for doc_id in doc_ids:
        try:
            chunks = await ctx.layer.get_pipeline_document_chunks(
                ctx.settings.reviews_pipeline_id, doc_id
            )
        except Exception:
            logger.exception("failed to prepare review document", extra={"doc_id": doc_id})
            release.append(doc_id)
            continue
        if not chunks:
            fail.append(doc_id)
            continue
        raw = chunks[0]
        metadata = raw.metadata or {}
        text = raw.text or ""
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
        classify_chunk = None
        if metadata.get("enqueue_classify") is True:
            classify_metadata = dict(metadata)
            classify_metadata.pop("enqueue_classify", None)
            classify_chunk = {
                "id": review_raw_chunk_id(review_id),
                "text": text,
                "metadata": classify_metadata,
            }
        prepared.append((doc_id, namespace, vector_items, classify_chunk))

    if not prepared:
        return StageOutcome(fail=fail, release=release)

    # Batch-encode across all (doc_id, vector_id, item) flat tuples, then
    # upsert per-doc so a single doc fully succeeds or fully releases.
    flat: list[tuple[str, dict[str, Any]]] = [
        (doc_id, item) for doc_id, _ns, items, _handoff in prepared for item in items
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

    upsertable = [
        (doc_id, namespace, items, classify_chunk)
        for doc_id, namespace, items, classify_chunk in prepared
        if doc_id not in release
        and items
        and not any("vector" not in item for item in items)
    ]
    if upsertable:
        # Issue upserts in parallel under a bounded semaphore. The previous
        # sequential await loop made the upsert phase the wall-clock
        # bottleneck (~200 ms/doc → ~7 min for a 2000-doc claim batch),
        # which routinely exceeded the claim lease and silently desynced
        # the pipeline-stage counter from the vectors that actually landed.
        sem = asyncio.Semaphore(ctx.settings.review_upsert_concurrency)

        async def _upsert_one(
            doc_id: str,
            namespace: str,
            items: list[dict[str, Any]],
            classify_chunk: dict[str, Any] | None,
        ) -> tuple[str, bool]:
            async with sem:
                try:
                    upserts = [
                        UpsertDocument(
                            id=item["id"],
                            vector=item.get("vector"),
                            attributes=item.get("attributes") or {},
                        )
                        for item in items
                    ]
                    await ctx.layer.upsert_documents(
                        namespace, UpsertRequest(upserts=upserts)
                    )
                    if classify_chunk is not None:
                        review_id = str(classify_chunk["metadata"]["review_id"])
                        await ctx.layer.put_pipeline_document_chunks(
                            ctx.settings.reviews_pipeline_id,
                            review_work_document_id("classify", review_id),
                            PutChunksRequest(
                                chunks=[
                                    Chunk(
                                        id=classify_chunk["id"],
                                        text=classify_chunk.get("text"),
                                        metadata=classify_chunk.get("metadata") or {},
                                    )
                                ]
                            ),
                        )
                    return doc_id, True
                except Exception:
                    logger.exception(
                        "failed to upsert review vector batch",
                        extra={"doc_id": doc_id, "namespace": namespace},
                    )
                    return doc_id, False

        results = await asyncio.gather(
            *(_upsert_one(*args) for args in upsertable)
        )
        for doc_id, ok in results:
            if ok:
                complete.append(doc_id)
            else:
                release.append(doc_id)

    return StageOutcome(complete=complete, fail=fail, release=release)


# ---------------------------------------------------------------------------
# Stage: classify-reviews  (OpenRouter tag classify → enqueue aggregate)
# ---------------------------------------------------------------------------

async def setup_classify_reviews(ctx: StageContext) -> None:
    await ctx.layer.ensure_pipeline(
        CreatePipelineRequest(
            id=ctx.settings.reviews_pipeline_id,
            target_namespace=ctx.settings.reviews_namespace_base,
            distance_metric=ctx.settings.distance_metric,
        )
    )
    await ctx.layer.ensure_pipeline(
        CreatePipelineRequest(
            id=ctx.settings.review_aggregate_pipeline_id,
            target_namespace=ctx.settings.namespace,
            distance_metric=ctx.settings.distance_metric,
        )
    )


async def process_classify_reviews(ctx: StageContext, doc_ids: list[str]) -> StageOutcome:
    # Behavior shift from the old worker: we claim then release when the
    # API key is missing (the old worker short-circuited before claiming).
    # End state is identical — no progress, no tag patches — at the cost
    # of one extra lease round-trip per idle tick.
    if not ctx.settings.openrouter_api_key:
        logger.warning("OPENROUTER_API_KEY is not set; releasing claimed review docs")
        return StageOutcome(release=list(doc_ids))

    fail: list[str] = []
    release: list[str] = []
    reviews: list[ReviewClassificationInput] = []
    doc_id_by_review: dict[str, str] = {}
    vector_ref_by_review: dict[str, tuple[str, str]] = {}

    for doc_id in doc_ids:
        try:
            chunks = await ctx.layer.get_pipeline_document_chunks(
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
        metadata = chunk.metadata or {}
        text = str(chunk.text or "").strip()
        asin = str(metadata.get("asin") or "")
        review_id = str(metadata.get("review_id") or "")
        if not asin or not review_id or not text:
            fail.append(doc_id)
            continue
        namespace = review_namespace_for(
            asin,
            namespace_base=ctx.settings.reviews_namespace_base,
            shard_count=ctx.settings.reviews_namespace_shard_count,
        )
        vector_id = review_chunk_vector_id(review_id)
        try:
            await ctx.layer.fetch_document(
                namespace,
                vector_id,
                include_attributes=["review_id"],
            )
        except Exception:
            logger.info(
                "review vector is not visible yet; releasing classification",
                extra={"doc_id": doc_id, "namespace": namespace, "vector_id": vector_id},
            )
            release.append(doc_id)
            continue
        doc_id_by_review[review_id] = doc_id
        vector_ref_by_review[review_id] = (namespace, vector_id)
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
    patches_by_namespace: dict[str, list[PatchDocument]] = {}
    classified_at = datetime.now(timezone.utc).isoformat()
    for review in reviews:
        tags = classified.get(review.review_id, [])
        namespace, vector_id = vector_ref_by_review[review.review_id]
        tag_names = [tag.tag for tag in tags if tag.tag in REVIEW_TAGS]
        confidences = {
            tag.tag: float(tag.confidence)
            for tag in tags
            if tag.tag in REVIEW_TAGS
        }
        patches_by_namespace.setdefault(namespace, []).append(
            PatchDocument(
                id=vector_id,
                attributes={
                    "tags": tag_names,
                    "tag_confidences": json.dumps(
                        confidences, separators=(",", ":")
                    ),
                    "review_classified_at": classified_at,
                },
            )
        )
        aggregate_asins.append(review.asin)
        complete.append(doc_id_by_review[review.review_id])

    try:
        for namespace, patches in patches_by_namespace.items():
            await ctx.layer.patch_documents(namespace, PatchRequest(patches=patches))
    except Exception:
        logger.exception("failed to patch review classification attrs")
        release.extend(doc_id_by_review[review.review_id] for review in reviews)
        return StageOutcome(fail=fail, release=release)

    # The cross-stage hand-off: transition the touched ASINs to `pending`
    # on the aggregate pipeline so the next-stage worker can pick them up.
    await ctx.layer.set_documents_stage(
        ctx.settings.review_aggregate_pipeline_id,
        SetDocumentsStageRequest(
            document_ids=sorted(set(aggregate_asins)),
            stage="pending",
            create_missing=True,
        ),
    )

    logger.info("classified %s reviews", len(reviews))
    return StageOutcome(complete=complete, fail=fail, release=release)


# ---------------------------------------------------------------------------
# Stage: aggregate-tags  (review namespace scan → PATCH product rows)
# ---------------------------------------------------------------------------

async def setup_aggregate_tags(ctx: StageContext) -> None:
    await ctx.layer.ensure_pipeline(
        CreatePipelineRequest(
            id=ctx.settings.review_aggregate_pipeline_id,
            target_namespace=ctx.settings.namespace,
            distance_metric=ctx.settings.distance_metric,
        )
    )


async def process_aggregate_tags(ctx: StageContext, asins: list[str]) -> StageOutcome:
    # `asins` are the claimed doc_ids — the aggregate pipeline indexes
    # rows by ASIN, so the driver abstraction doesn't notice the rename.
    try:
        patches: list[PatchDocument] = []
        for asin in asins:
            attrs = await aggregate_review_tag_attrs(
                ctx,
                asin,
                min_count=ctx.settings.review_tag_min_count,
                min_fraction=ctx.settings.review_tag_min_fraction,
                sample_count=ctx.settings.review_tag_sample_count,
            )
            patches.append(PatchDocument(id=asin, attributes=attrs))
        await ctx.layer.patch_documents(
            ctx.settings.namespace, PatchRequest(patches=patches)
        )
    except Exception:
        logger.exception("failed to aggregate review tags")
        return StageOutcome(release=list(asins))

    return StageOutcome(complete=list(asins))


def review_chunk_vector_id(review_id: str) -> str:
    return f"{review_id}:chunk:0000"


async def aggregate_review_tag_attrs(
    ctx: StageContext,
    asin: str,
    *,
    min_count: int,
    min_fraction: float,
    sample_count: int,
) -> dict[str, Any]:
    namespace = review_namespace_for(
        asin,
        namespace_base=ctx.settings.reviews_namespace_base,
        shard_count=ctx.settings.reviews_namespace_shard_count,
    )
    scan = await ctx.layer.scan(
        namespace,
        CreateScanRequest(
            scan_type="full_document",
            filters=["asin", "Eq", asin],
            page_size=ctx.settings.review_aggregate_scan_page_size,
        ),
    )
    results = await ctx.layer.get_scan_results(namespace, scan.id)

    classified: dict[str, dict[str, Any]] = {}
    for row in scan_result_rows(results):
        attrs = row_attrs(row)
        review_id = str(attrs.get("review_id") or "").strip()
        if not review_id:
            continue
        if "review_classified_at" not in attrs and "tags" not in attrs:
            continue
        classified.setdefault(review_id, attrs)

    total = len(classified)
    threshold = max(min_count, ceil(total * min_fraction)) if total else min_count
    tag_counts: dict[str, int] = {}
    sample_candidates: dict[str, list[tuple[float, str, str]]] = {}
    for review_id, attrs in classified.items():
        confidences = parse_tag_confidences(attrs.get("tag_confidences"))
        classified_at = str(attrs.get("review_classified_at") or "")
        for tag in coerce_review_tags(attrs.get("tags")):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
            sample_candidates.setdefault(tag, []).append(
                (float(confidences.get(tag, 0.0)), classified_at, review_id)
            )

    tags = [
        tag
        for tag, count in sorted(
            tag_counts.items(), key=lambda item: (-item[1], item[0])
        )
        if count >= threshold
    ]
    tag_samples: dict[str, list[str]] = {}
    for tag in tags:
        candidates = sorted(
            sample_candidates.get(tag, []),
            key=lambda item: (-item[0], item[1], item[2]),
        )
        tag_samples[tag] = [review_id for _conf, _at, review_id in candidates[:sample_count]]

    attrs: dict[str, Any] = {
        "tags": tags,
        "classified_review_count": total,
        "tag_threshold": threshold,
    }
    if tag_counts:
        attrs["tag_counts"] = json.dumps(tag_counts, separators=(",", ":"))
    if tag_samples:
        attrs["tag_samples"] = json.dumps(tag_samples, separators=(",", ":"))
    return attrs


def scan_result_rows(results: Any) -> list[dict[str, Any]]:
    # SDK returns a ScanResults pydantic model; `full_document` scans put
    # row dicts in `.results` rather than the typed FieldValueResult, so
    # normalise either shape (model or plain dict) to a list of dicts.
    if hasattr(results, "model_dump"):
        results = results.model_dump()
    rows = results.get("results") if isinstance(results, dict) else None
    if rows is None and isinstance(results, dict):
        rows = results.get("data")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def row_attrs(row: dict[str, Any]) -> dict[str, Any]:
    attrs = row.get("attributes")
    if isinstance(attrs, dict):
        return attrs
    return row


def parse_tag_confidences(value: Any) -> dict[str, float]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in parsed.items():
        try:
            out[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def coerce_review_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed = set(REVIEW_TAGS)
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        tag = str(item)
        if tag not in allowed or tag in seen:
            continue
        out.append(tag)
        seen.add(tag)
    return out


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
        setup=setup_embed_reviews,
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
    # "extract" stays separate because it expands one extraction job into
    # product/review documents, but it now claims those jobs from a Layer
    # pipeline too.
}


# ---------------------------------------------------------------------------
# Lazy embedder/classifier singletons (kept inline so a stage's deps are
# obvious from one read of this file)
# ---------------------------------------------------------------------------

def _clip_image(ctx: StageContext):
    if ctx._clip_image is None:
        from hev_shop_common.embedders import CLIPImageEmbedder
        ctx._clip_image = CLIPImageEmbedder(ctx.settings)
    return ctx._clip_image


def _qwen(ctx: StageContext):
    if ctx._qwen is None:
        from hev_shop_common.embedders import QwenTextEmbedder
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
    layer = AsyncHevlayer(
        api_key=settings.layer_api_key,
        base_url=settings.layer_gateway_url,
        timeout=settings.http_timeout_seconds,
    )
    ctx = StageContext(settings=settings, layer=layer)
    stop = asyncio.Event()
    _install_signals(stop)
    try:
        await run_stage(STAGES[stage_name], ctx, stop)
    finally:
        await layer.aclose()


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
