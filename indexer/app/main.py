from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request

from .config import get_settings
from .jobs import (
    EXTRACTION_JOB_CHUNK_ID,
    build_backfill_job,
    build_index_jobs,
    extraction_job_metadata,
)
from .layer_client import LayerClient
from .models import (
    BackfillRequest,
    BackfillResponse,
    CategoryBucket,
    IndexCategoryResponse,
    IndexRequest,
    IndexResponse,
    LayerPerf,
    MetaResponse,
    ProductResponse,
    ReviewSample,
    ReviewSamplesResponse,
    ReviewSearchResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StatusResponse,
)
from .records import (
    normalize_asin_list,
    normalize_backfill_stages,
    normalize_review_tags,
    review_namespace_for,
)

logger = logging.getLogger("hev_shop.indexer")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    layer = LayerClient(
        settings.layer_gateway_url,
        settings.http_timeout_seconds,
        api_key=settings.layer_api_key,
    )
    text_settings = (
        settings.model_copy(update={"model_cache_dir": settings.api_model_cache_dir})
        if settings.api_model_cache_dir is not None
        else settings
    )
    app.state.settings = settings
    app.state.text_embedder_settings = text_settings
    app.state.layer = layer
    app.state.text_embedder = None
    app.state.text_embedder_lock = asyncio.Lock()
    app.state.text_embedder_warm_task = None
    app.state.review_text_embedder = None
    app.state.review_text_embedder_lock = asyncio.Lock()
    app.state.meta_cache = {}
    app.state.meta_cache_lock = asyncio.Lock()
    if settings.prewarm_text_embedder:
        app.state.text_embedder_warm_task = asyncio.create_task(
            warm_text_embedder(app)
        )
    try:
        yield
    finally:
        warm_task = app.state.text_embedder_warm_task
        if warm_task is not None and not warm_task.done():
            warm_task.cancel()
        await layer.close()


async def get_text_embedder(app: FastAPI):
    if app.state.text_embedder is not None:
        return app.state.text_embedder
    async with app.state.text_embedder_lock:
        if app.state.text_embedder is None:
            from .embedders import CLIPTextEmbedder

            settings = getattr(app.state, "text_embedder_settings", app.state.settings)
            app.state.text_embedder = await asyncio.to_thread(
                CLIPTextEmbedder, settings
            )
        return app.state.text_embedder


async def warm_text_embedder(app: FastAPI) -> None:
    start = time.monotonic()
    try:
        await get_text_embedder(app)
        logger.info("text embedder warmed in %.3fs", time.monotonic() - start)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("text embedder warm failed")


async def get_review_text_embedder(app: FastAPI):
    if app.state.review_text_embedder is not None:
        return app.state.review_text_embedder
    async with app.state.review_text_embedder_lock:
        if app.state.review_text_embedder is None:
            from .embedders import QwenTextEmbedder

            app.state.review_text_embedder = await asyncio.to_thread(
                QwenTextEmbedder, app.state.settings
            )
        return app.state.review_text_embedder


def combine_filters(filters: list[list[object]]) -> list[object] | None:
    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return ["And", filters]


# Product vectors store `tag_counts` (dict[str, int]) and `tag_samples`
# (dict[str, list[str]]) as JSON strings because turbopuffer rejects nested
# objects on patch_rows. Decode them on the way out so API consumers see the
# original dict shape.
_JSON_DICT_ATTRS = ("tag_counts", "tag_samples")


def decode_dict_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    if not attrs:
        return {}
    out = dict(attrs)
    for key in _JSON_DICT_ATTRS:
        value = out.get(key)
        if isinstance(value, str):
            try:
                out[key] = json.loads(value)
            except (TypeError, ValueError):
                # Leave malformed values in place rather than 500ing — the
                # storefront's coercers will fall back to {} on bad shapes.
                pass
    return out


app = FastAPI(title="hev-shop indexer", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/index", response_model=IndexResponse)
async def index_products(request: Request, body: IndexRequest) -> IndexResponse:
    settings = request.app.state.settings
    layer: LayerClient = request.app.state.layer

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

    await layer.create_pipeline(pipeline_id, namespace, settings.distance_metric)
    await layer.create_pipeline(
        settings.extraction_pipeline_id,
        namespace,
        settings.distance_metric,
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
            await layer.stage_pipeline_document(
                settings.extraction_pipeline_id,
                job.id,
                chunks=[
                    {
                        "id": EXTRACTION_JOB_CHUNK_ID,
                        "text": "",
                        "metadata": extraction_job_metadata(job),
                    }
                ],
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
    layer: LayerClient = request.app.state.layer

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

    await layer.create_pipeline(
        settings.extraction_pipeline_id,
        namespace,
        settings.distance_metric,
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
    await layer.stage_pipeline_document(
        settings.extraction_pipeline_id,
        job.id,
        chunks=[
            {
                "id": EXTRACTION_JOB_CHUNK_ID,
                "text": "",
                "metadata": extraction_job_metadata(job),
            }
        ],
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


@app.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    settings = request.app.state.settings
    layer: LayerClient = request.app.state.layer
    namespace = body.namespace or settings.namespace
    include_attributes: list[str] | bool = body.include_attributes or True
    filters: list[list[object]] = []
    if body.category:
        filters.append(["category", "Eq", body.category])
    tags = normalize_review_tags(body.tags)
    if tags:
        filters.append(["tags", "ContainsAny", tags])

    embedder = await get_text_embedder(request.app)
    vector = await asyncio.to_thread(embedder.encode_text, body.query)
    try:
        layer_response, perf = await layer.query_namespace_with_perf(
            namespace=namespace,
            vector=vector,
            top_k=body.top_k,
            include_attributes=include_attributes,
            filters=combine_filters(filters),
        )
    except Exception as exc:
        # Never embed str(exc) in detail — upstream exceptions can carry
        # bearer tokens, secret URLs, or other sensitive bytes (see the
        # 2026-05-19 incident where httpx echoed the gateway key).
        logger.exception("search upstream failed: namespace=%s", namespace)
        raise HTTPException(status_code=502, detail="search upstream failed") from exc
    hits = [
        SearchHit(
            id=result["id"],
            dist=result.get("dist"),
            attributes=decode_dict_attrs(result.get("attributes")),
        )
        for result in layer_response.get("results", [])
    ]
    return SearchResponse(
        query=body.query,
        namespace=namespace,
        hits=hits,
        stable_as_of=layer_response.get("stable_as_of"),
        layer_perf=LayerPerf(
            latency_ms=perf.latency_ms,
            cache_status=perf.cache_status,
        ),
    )


@app.get("/product/{asin}", response_model=ProductResponse)
async def product(request: Request, asin: str) -> ProductResponse:
    settings = request.app.state.settings
    layer: LayerClient = request.app.state.layer
    try:
        document, perf = await layer.fetch_document_with_perf(
            settings.namespace,
            asin,
            include_attributes=[
                "asin",
                "title",
                "description",
                "category",
                "image_url",
                "avg_rating_txt",
                "rating_cnt_txt",
                "tags",
                "tag_counts",
                "tag_samples",
            ],
        )
    except Exception as exc:
        logger.exception("product fetch failed: asin=%s", asin)
        raise HTTPException(status_code=404, detail="product not found") from exc
    return ProductResponse(
        asin=asin,
        namespace=settings.namespace,
        attributes=decode_dict_attrs(document.get("attributes")),
        layer_perf=LayerPerf(
            latency_ms=perf.latency_ms,
            cache_status=perf.cache_status,
        ),
    )


@app.get("/search/reviews", response_model=ReviewSearchResponse)
async def search_reviews(
    request: Request,
    q: str,
    asin: str,
    top_k: int = 10,
    category: str | None = None,
) -> ReviewSearchResponse:
    if not q.strip():
        raise HTTPException(status_code=422, detail="q is required")
    if not asin.strip():
        raise HTTPException(status_code=422, detail="asin is required")
    if top_k < 1 or top_k > 200:
        raise HTTPException(status_code=422, detail="top_k must be between 1 and 200")

    settings = request.app.state.settings
    if not settings.api_review_search_enabled:
        raise HTTPException(
            status_code=503,
            detail="review search is disabled on this pod (Qwen-8B requires GPU)",
        )
    layer: LayerClient = request.app.state.layer
    namespace = review_namespace_for(
        asin,
        namespace_base=settings.resolved_reviews_query_namespace_base,
        shard_count=settings.reviews_namespace_shard_count,
    )
    filters: list[list[object]] = [["asin", "Eq", asin]]
    if category:
        filters.append(["category", "Eq", category])

    embedder = await get_review_text_embedder(request.app)
    vector = await asyncio.to_thread(embedder.encode_texts, [q])
    layer_response, perf = await layer.query_namespace_with_perf(
        namespace=namespace,
        vector=vector[0],
        top_k=top_k,
        include_attributes=[
            "asin",
            "review_id",
            "chunk_idx",
            "text_chunk",
            "category",
            "rating",
            "title",
            "helpful_vote",
        ],
        filters=combine_filters(filters),
    )
    hits = [
        SearchHit(
            id=result["id"],
            dist=result.get("dist"),
            attributes=result.get("attributes") or {},
        )
        for result in layer_response.get("results", [])
    ]
    return ReviewSearchResponse(
        query=q,
        namespace=namespace,
        asin=asin,
        category=category,
        hits=hits,
        stable_as_of=layer_response.get("stable_as_of"),
        layer_perf=LayerPerf(
            latency_ms=perf.latency_ms,
            cache_status=perf.cache_status,
        ),
    )


@app.get("/reviews/samples", response_model=ReviewSamplesResponse)
async def review_samples(
    request: Request,
    asin: str,
    ids: str,
) -> ReviewSamplesResponse:
    review_ids = [item.strip() for item in ids.split(",") if item.strip()]
    if not asin.strip():
        raise HTTPException(status_code=422, detail="asin is required")
    if not review_ids:
        return ReviewSamplesResponse(asin=asin, samples=[])

    settings = request.app.state.settings
    layer: LayerClient = request.app.state.layer
    samples: list[ReviewSample] = []
    for review_id in review_ids[:50]:
        namespace = review_namespace_for(
            asin,
            namespace_base=settings.reviews_namespace_base,
            shard_count=settings.reviews_namespace_shard_count,
        )
        try:
            document = await layer.fetch_document(
                namespace,
                f"{review_id}:chunk:0000",
                include_attributes=[
                    "asin",
                    "review_id",
                    "text_chunk",
                    "title",
                    "rating",
                ],
            )
        except Exception:
            continue
        attrs = document.get("attributes") or {}
        if str(attrs.get("asin") or "") != asin:
            continue
        text = str(attrs.get("text_chunk") or "").strip()
        if not text:
            continue
        samples.append(
            ReviewSample(
                review_id=review_id,
                asin=asin,
                title=attrs.get("title"),
                text=text[:600],
                rating=attrs.get("rating"),
            )
        )
    return ReviewSamplesResponse(asin=asin, samples=samples)


@app.get("/meta", response_model=MetaResponse)
async def meta(request: Request, namespace: str | None = None) -> MetaResponse:
    """Fan out to layer-gateway for namespace shape:
      - /v2/namespaces/{ns}/metadata → row count + freshness watermark
      - field_values scan on `category` → filterable category list
    """
    settings = request.app.state.settings
    layer: LayerClient = request.app.state.layer
    resolved_namespace = namespace or settings.namespace
    cache_ttl = max(settings.meta_cache_ttl_seconds, 0.0)
    cache_key = resolved_namespace

    if cache_ttl > 0:
        cached = request.app.state.meta_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_response = cached
            if time.monotonic() - cached_at < cache_ttl:
                return cached_response

    async with request.app.state.meta_cache_lock:
        if cache_ttl > 0:
            cached = request.app.state.meta_cache.get(cache_key)
            if cached is not None:
                cached_at, cached_response = cached
                if time.monotonic() - cached_at < cache_ttl:
                    return cached_response

        (metadata, metadata_perf), category_scan = await asyncio.gather(
            layer.fetch_namespace_metadata_with_perf(resolved_namespace),
            layer.scan(resolved_namespace, "field_values", field="category"),
        )

        category_results = await layer.get_scan_results(
            resolved_namespace, category_scan["id"]
        )
        categories = [
            CategoryBucket(value=row["value"], doc_count=row["doc_count"])
            for row in category_results.get("results", [])
        ]

        layer_block = metadata.get("layer") or {}
        response = MetaResponse(
            namespace=resolved_namespace,
            vectors=int(metadata.get("approx_row_count") or 0),
            categories=categories,
            stable_as_of=layer_block.get("stable_as_of"),
            is_stable=bool(layer_block.get("is_stable", False)),
            layer_perf=LayerPerf(
                latency_ms=metadata_perf.latency_ms,
                cache_status=metadata_perf.cache_status,
            ),
        )
        if cache_ttl > 0:
            request.app.state.meta_cache[cache_key] = (time.monotonic(), response)
        return response


@app.get("/status", response_model=StatusResponse)
async def status(request: Request, pipeline_id: str | None = None) -> StatusResponse:
    settings = request.app.state.settings
    layer: LayerClient = request.app.state.layer
    resolved_pipeline_id = pipeline_id or settings.default_pipeline_id

    layer_status = await layer.pipeline_status(resolved_pipeline_id)
    try:
        extraction_status = await layer.pipeline_status(settings.extraction_pipeline_id)
    except Exception:
        extraction_status = {}
    jobs = stage_counts_from_status(extraction_status)
    return StatusResponse(
        pipeline_id=resolved_pipeline_id,
        layer=layer_status,
        jobs=jobs,
        extraction=extraction_status,
    )


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
