"""hev-shop search API.

Read-only surface in front of Layer's vector gateway:

- POST /search           — text query → CLIP-text embedding → vector query
- GET  /product/{asin}   — document fetch (Aerospike-cached on the gateway)
- GET  /meta             — namespace metadata + per-category counts
- GET  /healthz          — liveness

The indexer control plane (POST /index, GET /status) lives in
`../indexer/app/`. Everything shared (Settings, records, embedders) is in
`hev_shop_common`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from hevlayer import (
    AsyncHevlayer,
    ResultCountRequest,
    CreateSnapshotRequest,
    QueryRequest,
    VectorResultCountQuery,
)

from hev_shop_common.config import get_settings
from .models import (
    CategoryBucket,
    CountInfo,
    LayerPerf,
    MetaResponse,
    ProductResponse,
    RecommendRequest,
    RecommendResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
)

logger = logging.getLogger("hev_shop.search")

SEARCH_HISTORY_BASE_TAGS = ("app:hev-shop", "surface:storefront", "route:search")
SEARCH_HISTORY_SURFACE_HEADER = "x-hev-shop-surface"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    layer = AsyncHevlayer(
        api_key=settings.layer_api_key,
        base_url=settings.layer_gateway_url,
        timeout=settings.http_timeout_seconds,
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
        await layer.aclose()


async def get_text_embedder(app: FastAPI):
    if app.state.text_embedder is not None:
        return app.state.text_embedder
    async with app.state.text_embedder_lock:
        if app.state.text_embedder is None:
            from hev_shop_common.embedders import CLIPTextEmbedder

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


async def wait_for_snapshot_job(
    layer: AsyncHevlayer,
    namespace: str,
    job_id: str,
    *,
    timeout: float | None,
    initial_delay: float = 0.05,
    max_delay: float = 2.0,
):
    started = time.monotonic()
    delay = initial_delay
    while True:
        job = await layer.get_snapshot_job(namespace, job_id)
        if job.status == "completed":
            return job
        if job.status == "failed":
            raise RuntimeError(
                f"snapshot job {job_id!r} failed: {job.error or 'unknown error'}"
            )
        if timeout is not None and time.monotonic() - started >= timeout:
            raise TimeoutError(f"snapshot job {job_id!r} did not finish")
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)


async def get_field_snapshot(
    layer: AsyncHevlayer,
    namespace: str,
    field: str,
    *,
    timeout: float | None,
):
    job = await layer.create_snapshot(
        namespace,
        CreateSnapshotRequest(field=field),
    )
    if job.status != "completed":
        job = await wait_for_snapshot_job(
            layer,
            namespace,
            job.id,
            timeout=timeout,
        )
    if not job.sha:
        raise RuntimeError(f"snapshot job {job.id!r} completed without a sha")
    return await layer.get_namespace_snapshot(namespace, job.sha)


def combine_filters(filters: list[list[object]]) -> list[object] | None:
    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return ["And", filters]


def decode_dict_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    return dict(attrs or {})


async def _vector_count(
    layer: AsyncHevlayer,
    namespace: str,
    vector: list[float],
    max_distance: float,
    filters: list[object] | None,
    *,
    label: str,
) -> CountInfo | None:
    """Best-effort fan-out to /v2/namespaces/{ns}/result-count. On failure the
    handler still returns hits — count is supplementary signal, not the
    contract."""
    try:
        response = await layer.result_count(
            namespace,
            ResultCountRequest(
                query=VectorResultCountQuery(vector=vector, max_distance=max_distance),
                filters=filters,
            ),
            with_perf=True,
        )
    except Exception:
        logger.exception("%s count upstream failed: namespace=%s", label, namespace)
        return None
    data = response.data
    return CountInfo(
        count=int(data.count),
        bounded=bool(data.bounded),
        timed_out=bool(data.timed_out),
        shards_saturated=int(data.shards_saturated),
        shards_total=int(data.shards_total),
        max_distance=max_distance,
        layer_perf=LayerPerf(
            latency_ms=int(response.perf.latency_ms),
            cache_status=response.perf.cache_status,
        ),
    )


def _extract_next_cursor(payload: Any) -> str | None:
    """QueryResponse may carry `next_cursor` as a typed field or as an
    extra (older SDK builds). Check both so this keeps working across
    SDK versions."""
    cursor = getattr(payload, "next_cursor", None)
    if cursor is None:
        extra = getattr(payload, "model_extra", None) or {}
        cursor = extra.get("next_cursor")
    if isinstance(cursor, str) and cursor:
        return cursor
    return None


def _search_history_kwargs(
    query: str, *, cursor: str | None, surface: str | None
) -> dict[str, Any]:
    if cursor or surface != "storefront":
        return {}
    return {
        "raw_query": query,
        "tags": [*SEARCH_HISTORY_BASE_TAGS, "page:first"],
    }


app = FastAPI(title="hev-shop search", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer
    namespace = body.namespace or settings.namespace
    include_attributes: list[str] | bool = body.include_attributes or True
    filters: list[list[object]] = []
    if body.category:
        filters.append(["category", "Eq", body.category])
    combined_filters = combine_filters(filters)

    embedder = await get_text_embedder(request.app)
    vector = await asyncio.to_thread(embedder.encode_text, body.query)
    query_kwargs: dict[str, Any] = {
        "vector": vector,
        "top_k": body.top_k,
        "include_attributes": include_attributes,
        "filters": combined_filters,
    }
    if body.cursor:
        query_kwargs["cursor"] = body.cursor
    try:
        query_task = layer.query_namespace(
            namespace,
            QueryRequest(**query_kwargs),
            **_search_history_kwargs(
                body.query,
                cursor=body.cursor,
                surface=request.headers.get(SEARCH_HISTORY_SURFACE_HEADER),
            ),
            with_perf=True,
        )
        if body.with_count:
            response, count_info = await asyncio.gather(
                query_task,
                _vector_count(
                    layer,
                    namespace,
                    vector,
                    body.max_distance,
                    combined_filters,
                    label="search",
                ),
            )
        else:
            response = await query_task
            count_info = None
    except Exception as exc:
        # Never embed str(exc) in detail — upstream exceptions can carry
        # bearer tokens, secret URLs, or other sensitive bytes (see the
        # 2026-05-19 incident where httpx echoed the gateway key).
        logger.exception("search upstream failed: namespace=%s", namespace)
        raise HTTPException(status_code=502, detail="search upstream failed") from exc
    hits = [
        SearchHit(
            id=result.id,
            dist=result.dist,
            attributes=decode_dict_attrs(result.attributes),
        )
        for result in response.data.results
    ]
    return SearchResponse(
        query=body.query,
        namespace=namespace,
        hits=hits,
        stable_as_of=response.data.stable_as_of,
        layer_perf=LayerPerf(
            latency_ms=int(response.perf.latency_ms),
            cache_status=response.perf.cache_status,
        ),
        next_cursor=_extract_next_cursor(response.data),
        count=count_info,
    )


@app.post("/recommend", response_model=RecommendResponse)
async def recommend(request: Request, body: RecommendRequest) -> RecommendResponse:
    """Visual-similarity recommendations seeded by an existing product ASIN.

    Uses Layer's `nearest_to_id` query mode: the gateway looks up the seed
    document's stored vector and runs the nearest-neighbor query in one call.
    The seed ASIN itself is filtered out so callers don't get the seed back
    as its own first hit.
    """
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer
    namespace = body.namespace or settings.namespace
    include_attributes: list[str] | bool = body.include_attributes or True
    filters: list[list[object]] = [["id", "NotEq", body.asin]]
    if body.category:
        filters.append(["category", "Eq", body.category])
    combined_filters = combine_filters(filters)

    try:
        response = await layer.query_namespace(
            namespace,
            QueryRequest(
                nearest_to_id=body.asin,
                top_k=body.top_k,
                include_attributes=include_attributes,
                filters=combined_filters,
            ),
            with_perf=True,
        )
    except Exception as exc:
        # See /search note: never put str(exc) in detail — upstream errors
        # can carry bearer tokens or signed URLs.
        logger.exception(
            "recommend upstream failed: namespace=%s asin=%s", namespace, body.asin
        )
        raise HTTPException(
            status_code=502, detail="recommend upstream failed"
        ) from exc

    hits = [
        SearchHit(
            id=result.id,
            dist=result.dist,
            attributes=decode_dict_attrs(result.attributes),
        )
        for result in response.data.results
    ]
    return RecommendResponse(
        asin=body.asin,
        namespace=namespace,
        hits=hits,
        stable_as_of=response.data.stable_as_of,
        layer_perf=LayerPerf(
            latency_ms=int(response.perf.latency_ms),
            cache_status=response.perf.cache_status,
        ),
        next_cursor=_extract_next_cursor(response.data),
    )


@app.get("/product/{asin}", response_model=ProductResponse)
async def product(request: Request, asin: str) -> ProductResponse:
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer
    try:
        response = await layer.fetch_document(
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
            ],
            with_perf=True,
        )
    except Exception as exc:
        logger.exception("product fetch failed: asin=%s", asin)
        raise HTTPException(status_code=404, detail="product not found") from exc
    return ProductResponse(
        asin=asin,
        namespace=settings.namespace,
        attributes=decode_dict_attrs(response.data.attributes),
        layer_perf=LayerPerf(
            latency_ms=int(response.perf.latency_ms),
            cache_status=response.perf.cache_status,
        ),
    )


@app.get("/meta", response_model=MetaResponse)
async def meta(request: Request, namespace: str | None = None) -> MetaResponse:
    """Fan out to layer-gateway for namespace shape:
      - /v2/namespaces/{ns}/metadata → row count + freshness watermark
      - on-demand snapshot on `category` → filterable category list
    """
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer
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

        metadata_response, category_snapshot = await asyncio.gather(
            layer.get_namespace_metadata(resolved_namespace, with_perf=True),
            get_field_snapshot(
                layer,
                resolved_namespace,
                "category",
                timeout=settings.http_timeout_seconds,
            ),
        )

        categories = [
            CategoryBucket(value=value.v, doc_count=value.n)
            for field in category_snapshot.fields
            if field.name == "category"
            for value in field.values
        ]

        metadata = metadata_response.data
        layer_block = (metadata.model_extra or {}).get("layer") or {}
        response = MetaResponse(
            namespace=resolved_namespace,
            vectors=int(metadata.approx_row_count or 0),
            categories=categories,
            stable_as_of=layer_block.get("stable_as_of"),
            is_stable=bool(layer_block.get("is_stable", False)),
            layer_perf=LayerPerf(
                latency_ms=int(metadata_response.perf.latency_ms),
                cache_status=metadata_response.perf.cache_status,
            ),
        )
        if cache_ttl > 0:
            request.app.state.meta_cache[cache_key] = (time.monotonic(), response)
        return response
