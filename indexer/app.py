"""hev-shop indexer control plane.

Routes:

- POST /index     — enqueue extraction jobs for one or more categories
- GET  /status    — pipeline stage counts (read-only; sibling to the read API)
- GET  /healthz   — liveness

This is the only place that creates the two Layer queues. The workers that
drain them are declared as Pipeline resources in `pipelines/` and run
`extract_chunk.py` / `embed.py`; the Layer operator owns their Deployments
and scaling. The storefront's read surface (/search, /product, /meta, …)
lives in `../search/`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from hevlayer import (
    AsyncHevlayer,
    Chunk,
    CreatePipelineRequest,
    HevlayerError,
    PutChunksRequest,
)
from pydantic import BaseModel, Field

from hev_shop_common.config import get_settings
from hev_shop_common.records import dedupe_categories

from extract_chunk import (
    EXTRACTION_JOB_CHUNK_ID,
    build_index_jobs,
    extraction_job_metadata,
)

logger = logging.getLogger("hev_shop.indexer")


# --- HTTP contracts ---------------------------------------------------------


class IndexRequest(BaseModel):
    count: int = Field(default=100, description="-1 indexes all rows in one job")
    category: str | None = None
    categories: list[str] | None = Field(
        default=None,
        description=(
            "Optional multi-category fan-out. Overrides category unless "
            "category is explicitly merged by the caller."
        ),
    )
    job_size: int | None = None
    catalog_run_id: str | None = Field(
        default=None,
        description=(
            "Catalog drop/run identifier stamped onto every staged product "
            "vector. Defaults to catalog-YYYY-MM-DD in UTC."
        ),
    )

    def resolved_categories(self, default_category: str) -> list[str]:
        if self.categories is not None:
            categories = self.categories
        else:
            categories = [self.category or default_category]
        return dedupe_categories(categories)

    def resolved_catalog_run_id(self) -> str:
        value = (self.catalog_run_id or "").strip()
        return value or default_catalog_run_id()


def default_catalog_run_id(now: datetime | None = None) -> str:
    at = now or datetime.now(timezone.utc)
    return f"catalog-{at.date().isoformat()}"


class IndexCategoryResponse(BaseModel):
    category: str
    count: int
    jobs_created: int


class IndexResponse(BaseModel):
    pipeline_id: str
    namespace: str
    catalog_run_id: str
    category: str
    count: int
    jobs_created: int
    categories: list[IndexCategoryResponse] = Field(default_factory=list)


class StatusResponse(BaseModel):
    pipeline_id: str
    layer: dict[str, Any]
    jobs: dict[str, int]
    extraction: dict[str, Any] = Field(default_factory=dict)


# --- App --------------------------------------------------------------------


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

    pipeline_id = settings.default_pipeline_id
    namespace = settings.namespace
    job_size = body.job_size or settings.extraction_job_size
    categories = body.resolved_categories(settings.default_category)
    catalog_run_id = body.resolved_catalog_run_id()
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
            catalog_run_id=catalog_run_id,
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
        catalog_run_id=catalog_run_id,
        category=category_results[0].category,
        count=body.count,
        jobs_created=sum(result.jobs_created for result in category_results),
        categories=category_results,
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
