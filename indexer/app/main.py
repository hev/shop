from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request

from .config import get_settings
from .database import Database
from .layer_client import LayerClient
from .models import (
    BackfillRequest,
    BackfillResponse,
    CategoryBucket,
    IndexCategoryResponse,
    IndexRequest,
    IndexResponse,
    MetaResponse,
    ProductResponse,
    ReviewSample,
    ReviewSamplesResponse,
    ReviewSearchResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    StatusResponse,
    normalize_asin_list,
    normalize_backfill_stages,
    normalize_review_tags,
)
from .reviews import review_namespace_for, review_work_document_id


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = await Database.connect(settings.layer_database_url)
    await database.ensure_schema()
    layer = LayerClient(settings.layer_gateway_url, settings.http_timeout_seconds)
    app.state.settings = settings
    app.state.database = database
    app.state.layer = layer
    app.state.text_embedder = None
    app.state.text_embedder_lock = asyncio.Lock()
    app.state.review_text_embedder = None
    app.state.review_text_embedder_lock = asyncio.Lock()
    try:
        yield
    finally:
        await layer.close()
        await database.close()


async def get_text_embedder(app: FastAPI):
    if app.state.text_embedder is not None:
        return app.state.text_embedder
    async with app.state.text_embedder_lock:
        if app.state.text_embedder is None:
            from .embedders import CLIPTextEmbedder

            app.state.text_embedder = await asyncio.to_thread(
                CLIPTextEmbedder, app.state.settings
            )
        return app.state.text_embedder


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
    database: Database = request.app.state.database
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
    category_results: list[IndexCategoryResponse] = []
    for category in categories:
        jobs_created = await database.enqueue_index_jobs(
            pipeline_id=pipeline_id,
            namespace=namespace,
            category=category,
            count=body.count,
            job_size=job_size,
            max_retries=settings.max_job_retries,
        )
        category_results.append(
            IndexCategoryResponse(
                category=category,
                count=body.count,
                jobs_created=jobs_created,
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
    database: Database = request.app.state.database

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

    job_id = await database.enqueue_backfill_job(
        pipeline_id=pipeline_id,
        namespace=namespace,
        category=category,
        product_limit=body.product_limit,
        target_asins=asins,
        reviews_per_product=body.reviews_per_product,
        max_total_reviews=body.max_total_reviews,
        stages=stages,
        max_retries=settings.max_job_retries,
    )

    return BackfillResponse(
        job_id=job_id,
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
        layer_response = await layer.query_namespace(
            namespace=namespace,
            vector=vector,
            top_k=body.top_k,
            include_attributes=include_attributes,
            filters=combine_filters(filters),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
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
    )


@app.get("/product/{asin}", response_model=ProductResponse)
async def product(request: Request, asin: str) -> ProductResponse:
    settings = request.app.state.settings
    layer: LayerClient = request.app.state.layer
    try:
        document = await layer.fetch_document(
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProductResponse(
        asin=asin,
        namespace=settings.namespace,
        attributes=decode_dict_attrs(document.get("attributes")),
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
    layer: LayerClient = request.app.state.layer
    namespace = review_namespace_for(
        asin,
        namespace_base=settings.reviews_namespace_base,
        shard_count=settings.reviews_namespace_shard_count,
    )
    filters: list[list[object]] = [["asin", "Eq", asin]]
    if category:
        filters.append(["category", "Eq", category])

    embedder = await get_review_text_embedder(request.app)
    vector = await asyncio.to_thread(embedder.encode_texts, [q])
    layer_response = await layer.query_namespace(
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
        try:
            chunks = await layer.get_chunks(
                settings.reviews_pipeline_id,
                review_work_document_id("classify", review_id),
            )
        except Exception:
            continue
        if not chunks:
            continue
        chunk = chunks[0]
        metadata = chunk.get("metadata") or {}
        if str(metadata.get("asin") or "") != asin:
            continue
        text = str(chunk.get("text") or "").strip()
        samples.append(
            ReviewSample(
                review_id=review_id,
                asin=asin,
                title=metadata.get("title"),
                text=text[:600],
                rating=metadata.get("rating"),
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

    metadata, category_scan = await asyncio.gather(
        layer.fetch_namespace_metadata(resolved_namespace),
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
    return MetaResponse(
        namespace=resolved_namespace,
        vectors=int(metadata.get("approx_row_count") or 0),
        categories=categories,
        stable_as_of=layer_block.get("stable_as_of"),
        is_stable=bool(layer_block.get("is_stable", False)),
    )


@app.get("/status", response_model=StatusResponse)
async def status(request: Request, pipeline_id: str | None = None) -> StatusResponse:
    settings = request.app.state.settings
    database: Database = request.app.state.database
    layer: LayerClient = request.app.state.layer
    resolved_pipeline_id = pipeline_id or settings.default_pipeline_id

    layer_status = await layer.pipeline_status(resolved_pipeline_id)
    jobs = await database.index_job_counts(resolved_pipeline_id)
    return StatusResponse(
        pipeline_id=resolved_pipeline_id,
        layer=layer_status,
        jobs=jobs,
    )
