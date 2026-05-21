"""hev-shop indexer control plane.

Three routes:

- POST /index     — enqueue extraction jobs for one or more categories
- POST /backfill  — re-stage reviews / re-run aggregation for known products
- GET  /status    — pipeline stage counts (read-only; sibling to the read API)
- GET  /healthz   — liveness

The actual ingest work happens in worker processes that share this image
but boot via `app.worker` rather than this FastAPI app — see
`worker.STAGE_FOR_WORKER_TYPE`. The storefront's read surface (/search,
/product, /meta, …) lives in `../search/` and shares no FastAPI app
instance with this one.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from hevlayer import (
    AsyncHevlayer,
    Chunk,
    CreatePipelineRequest,
    HevlayerError,
    PutChunksRequest,
)

from hev_shop_common.config import get_settings
from hev_shop_common.records import (
    normalize_asin_list,
    normalize_backfill_stages,
)

from .jobs import (
    EXTRACTION_JOB_CHUNK_ID,
    build_backfill_job,
    build_index_jobs,
    extraction_job_metadata,
)
from .models import (
    BackfillRequest,
    BackfillResponse,
    IndexCategoryResponse,
    IndexRequest,
    IndexResponse,
    StatusResponse,
)

logger = logging.getLogger("hev_shop.indexer")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    layer = AsyncHevlayer(
        api_key=settings.layer_api_key,
        base_url=settings.layer_gateway_url,
        timeout=settings.http_timeout_seconds,
    )
    app.state.settings = settings
    app.state.layer = layer
    try:
        yield
    finally:
        await layer.aclose()


app = FastAPI(title="hev-shop indexer", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/index", response_model=IndexResponse)
async def index_products(request: Request, body: IndexRequest) -> IndexResponse:
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer

    pipeline_id = body.pipeline_id or settings.default_pipeline_id
    namespace = body.namespace or settings.namespace
    job_size = body.job_size or settings.extraction_job_size
    categories = body.resolved_categories(settings.default_category)
    if not categories:
        raise HTTPException(status_code=422, detail="at least one category is required")
    if body.count < -1:
        raise HTTPException(status_code=422, detail="count must be -1 or non-negative")
    if job_size <= 0:
        raise HTTPException(status_code=422, detail="job_size must be positive")

    await layer.ensure_pipeline(
        CreatePipelineRequest(
            id=pipeline_id,
            target_namespace=namespace,
            distance_metric=settings.distance_metric,
        )
    )
    await layer.ensure_pipeline(
        CreatePipelineRequest(
            id=settings.extraction_pipeline_id,
            target_namespace=namespace,
            distance_metric=settings.distance_metric,
        )
    )
    category_results: list[IndexCategoryResponse] = []
    for category in categories:
        jobs = build_index_jobs(
            pipeline_id=pipeline_id,
            namespace=namespace,
            category=category,
            count=body.count,
            job_size=job_size,
        )
        for job in jobs:
            await layer.put_pipeline_document_chunks(
                settings.extraction_pipeline_id,
                job.id,
                PutChunksRequest(
                    chunks=[
                        Chunk(
                            id=EXTRACTION_JOB_CHUNK_ID,
                            text="",
                            metadata=extraction_job_metadata(job),
                        )
                    ]
                ),
            )
        category_results.append(
            IndexCategoryResponse(
                category=category,
                count=body.count,
                jobs_created=len(jobs),
            )
        )

    return IndexResponse(
        pipeline_id=pipeline_id,
        namespace=namespace,
        category=category_results[0].category,
        count=body.count,
        jobs_created=sum(result.jobs_created for result in category_results),
        categories=category_results,
    )


@app.post("/backfill", response_model=BackfillResponse)
async def backfill(request: Request, body: BackfillRequest) -> BackfillResponse:
    """Enqueue a backfill job that re-stages reviews (and optionally re-runs
    aggregation) for products already in the namespace. The CPU extraction
    worker picks the job up and uses the layer-gateway pipelines that the
    review-embed / review-classify / review-aggregate workers already consume."""
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer

    category = body.category.strip()
    if not category:
        raise HTTPException(status_code=422, detail="category is required")

    asins = normalize_asin_list(body.asins)
    if body.product_limit < -1:
        raise HTTPException(
            status_code=422, detail="product_limit must be -1 or non-negative"
        )
    if asins is not None and not asins:
        raise HTTPException(
            status_code=422, detail="asins must contain at least one entry when provided"
        )
    if body.reviews_per_product is not None and body.reviews_per_product < 0:
        raise HTTPException(
            status_code=422, detail="reviews_per_product must be >= 0"
        )
    if body.max_total_reviews is not None and body.max_total_reviews < 0:
        raise HTTPException(
            status_code=422, detail="max_total_reviews must be >= 0"
        )

    stages = normalize_backfill_stages(body.stages)
    if not stages:
        raise HTTPException(
            status_code=422,
            detail="stages must include at least one of embed/classify/aggregate",
        )

    pipeline_id = body.pipeline_id or settings.default_pipeline_id
    namespace = body.namespace or settings.namespace

    await layer.ensure_pipeline(
        CreatePipelineRequest(
            id=settings.extraction_pipeline_id,
            target_namespace=namespace,
            distance_metric=settings.distance_metric,
        )
    )
    job = build_backfill_job(
        pipeline_id=pipeline_id,
        namespace=namespace,
        category=category,
        product_limit=body.product_limit,
        target_asins=asins,
        reviews_per_product=body.reviews_per_product,
        max_total_reviews=body.max_total_reviews,
        stages=stages,
    )
    await layer.put_pipeline_document_chunks(
        settings.extraction_pipeline_id,
        job.id,
        PutChunksRequest(
            chunks=[
                Chunk(
                    id=EXTRACTION_JOB_CHUNK_ID,
                    text="",
                    metadata=extraction_job_metadata(job),
                )
            ]
        ),
    )

    return BackfillResponse(
        job_id=job.id,
        pipeline_id=pipeline_id,
        namespace=namespace,
        category=category,
        asin_count=len(asins) if asins is not None else None,
        product_limit=body.product_limit,
        reviews_per_product=body.reviews_per_product,
        max_total_reviews=body.max_total_reviews,
        stages=stages,
    )


@app.get("/status", response_model=StatusResponse)
async def status(request: Request, pipeline_id: str | None = None) -> StatusResponse:
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer
    resolved_pipeline_id = pipeline_id or settings.default_pipeline_id

    layer_status = await pipeline_status_or_empty(layer, resolved_pipeline_id)
    try:
        extraction_status = await pipeline_status_or_empty(
            layer, settings.extraction_pipeline_id
        )
    except Exception:
        extraction_status = {}
    jobs = stage_counts_from_status(extraction_status)
    return StatusResponse(
        pipeline_id=resolved_pipeline_id,
        layer=layer_status,
        jobs=jobs,
        extraction=extraction_status,
    )


async def pipeline_status_or_empty(
    layer: AsyncHevlayer, pipeline_id: str
) -> dict[str, Any]:
    try:
        return (await layer.get_pipeline_status(pipeline_id)).model_dump()
    except HevlayerError as exc:
        if exc.status_code != 404:
            raise
        return {
            "pipeline_id": pipeline_id,
            "counts": {},
            "pending_count": 0,
            "processing_count": 0,
            "failed_count": 0,
            "indexed_rate_per_min": 0.0,
            "rate_window_seconds": 0,
        }


def stage_counts_from_status(status: dict[str, Any]) -> dict[str, int]:
    for key in ("stages", "stage_counts", "counts"):
        value = status.get(key)
        if isinstance(value, dict):
            return {str(k): int(v) for k, v in value.items() if isinstance(v, int)}
        if isinstance(value, list):
            out: dict[str, int] = {}
            for row in value:
                if not isinstance(row, dict):
                    continue
                stage = row.get("stage")
                count = row.get("count")
                if stage is not None and isinstance(count, int):
                    out[str(stage)] = count
            return out
    return {str(k): int(v) for k, v in status.items() if isinstance(v, int)}
