"""hev-shop search API.

Read-only surface in front of Layer's vector gateway:

- POST /search           — text query → CLIP-text embedding → vector query
- GET  /product/{asin}   — document fetch (Aerospike-cached on the gateway)
- GET  /meta             — namespace metadata + per-category counts
- GET  /healthz          — liveness

The indexer control plane (POST /index, GET /status) lives in
`../indexer/`. Everything shared (Settings, records, embedders) is in
`hev_shop_common`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query as FastAPIQuery, Request
from hevlayer import (
    AnnScan,
    AsyncHevlayer,
    CreateScanRequest,
    CreateSnapshotRequest,
    QueryRequest,
)

from hev_shop_common.config import get_settings
from models import (
    CategoryBucket,
    CountInfo,
    DropInfo,
    DropsResponse,
    LayerPerf,
    MetaResponse,
    ProductResponse,
    RecommendRequest,
    RecommendResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    TrendingEntry,
    TrendingResponse,
)

logger = logging.getLogger("hev_shop.search")

SEARCH_HISTORY_BASE_TAGS = ("app:hev-shop", "surface:storefront", "route:search")
SEARCH_HISTORY_SURFACE_HEADER = "x-hev-shop-surface"
CHECKPOINT_LOOKUP_LIMIT = 100
PRODUCT_INCLUDE_ATTRIBUTES = [
    "asin",
    "title",
    "description",
    "category",
    "image_url",
    "image_blob",
    "avg_rating_txt",
    "rating_cnt_txt",
]
DROP_SCAN_CURSOR_PREFIX = "scan:"
DROP_BROWSE_CURSOR_PREFIX = "id:"


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


def temporal_between_filters(window: tuple[int, int]) -> list[list[object]]:
    lo, hi = window
    return [
        ["_hevlayer_upserted_at", "Gt", lo],
        ["_hevlayer_upserted_at", "Lte", hi],
    ]


def decode_dict_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    return dict(attrs or {})


def query_hits(payload: Any) -> list[SearchHit]:
    """Normalize current upstream-shaped `rows` and older Layer `results`."""
    rows = getattr(payload, "rows", None)
    if isinstance(rows, list):
        return [row_to_hit(row) for row in rows]

    results = getattr(payload, "results", None)
    if isinstance(results, list):
        return [
            SearchHit(
                id=str(result.id),
                dist=getattr(result, "dist", None),
                attributes=decode_dict_attrs(getattr(result, "attributes", None)),
            )
            for result in results
        ]
    return []


def row_to_hit(row: Any) -> SearchHit:
    if not isinstance(row, dict):
        return SearchHit(id="", attributes={})
    doc_id = str(row.get("id") or "")
    dist = row.get("$dist", row.get("dist"))
    attributes = row.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {
            key: value
            for key, value in row.items()
            if key not in {"id", "$dist", "dist", "vector"}
            and not key.startswith("$")
        }
    return SearchHit(
        id=doc_id,
        dist=dist if isinstance(dist, (int, float)) else None,
        attributes=decode_dict_attrs(attributes),
    )


def document_to_hit(document: Any) -> SearchHit:
    doc_id = str(getattr(document, "id", ""))
    return SearchHit(
        id=doc_id,
        attributes=decode_dict_attrs(getattr(document, "attributes", None)),
    )


def _int_value(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _float_value(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _query_rows(payload: Any) -> list[dict[str, Any]]:
    rows = getattr(payload, "rows", None)
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _stable_as_of(payload: Any) -> int | None:
    value = getattr(payload, "stable_as_of", None)
    if isinstance(value, int):
        return value
    extra = getattr(payload, "model_extra", None) or {}
    value = extra.get("stable_as_of")
    return value if isinstance(value, int) else None


def _layer_block(payload: Any) -> dict[str, Any]:
    value = getattr(payload, "layer", None)
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    extra = getattr(payload, "model_extra", None) or {}
    value = extra.get("layer")
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


async def _vector_count(
    layer: AsyncHevlayer,
    namespace: str,
    vector: list[float],
    max_distance: float,
    filters: list[object] | None,
    window: tuple[int, int] | None = None,
    *,
    label: str,
) -> CountInfo | None:
    """Best-effort fan-out to /v2/namespaces/{ns}/scans. On failure the
    handler still returns hits — count is supplementary signal, not the
    contract."""
    try:
        response = await layer.create_scan(
            namespace,
            CreateScanRequest(
                mode="count",
                ann=AnnScan(vector=vector, radius=max_distance),
                filters=filters,
                between=list(window) if window else None,
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
        shards_saturated=int(data.shards_saturated or 0),
        shards_total=int(data.shards_total or 0),
        approximate=bool(data.approximate),
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


def _drop_scan_cursor(cursor: str | None) -> tuple[str | None, int]:
    if not cursor:
        return (None, 0)
    if cursor.startswith(DROP_SCAN_CURSOR_PREFIX):
        parts = cursor.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise HTTPException(
                status_code=422,
                detail="catalog browse cursor must be a scan cursor",
            )
        _, scan_id, offset = parts
        return (scan_id, _positive_offset(offset))
    return (None, _positive_offset(cursor))


def _positive_offset(value: str) -> int:
    try:
        offset = int(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="catalog browse cursor must be a non-negative offset cursor",
        ) from exc
    if offset < 0:
        raise HTTPException(
            status_code=422,
            detail="catalog browse cursor must be a non-negative offset cursor",
        )
    return offset


def _scan_next_cursor(scan_id: str, offset: int, returned: int, total: int) -> str | None:
    next_offset = offset + returned
    if returned <= 0 or next_offset >= total:
        return None
    return f"{DROP_SCAN_CURSOR_PREFIX}{scan_id}:{next_offset}"


def _drop_browse_cursor_id(cursor: str | None) -> str | None:
    if not cursor:
        return None
    if cursor.startswith(DROP_BROWSE_CURSOR_PREFIX):
        cursor = cursor[len(DROP_BROWSE_CURSOR_PREFIX) :]
    if not cursor:
        raise HTTPException(status_code=422, detail="catalog browse cursor is empty")
    return cursor


def _drop_browse_next_cursor(rows: list[dict[str, Any]], limit: int) -> str | None:
    if len(rows) <= limit:
        return None
    doc_id = str(rows[limit - 1].get("id") or "")
    if not doc_id:
        return None
    return f"{DROP_BROWSE_CURSOR_PREFIX}{doc_id}"


async def checkpoint_window(
    layer: AsyncHevlayer,
    namespace: str,
    label: str,
) -> tuple[int, int]:
    page = await layer.list_checkpoints(namespace, limit=CHECKPOINT_LOOKUP_LIMIT)
    checkpoints = list(getattr(page, "checkpoints", []) or [])
    for index, checkpoint in enumerate(checkpoints):
        if getattr(checkpoint, "label", None) != label:
            continue
        hi = int(getattr(checkpoint, "watermark_ms"))
        lo = (
            int(getattr(checkpoints[index + 1], "watermark_ms"))
            if index + 1 < len(checkpoints)
            else 0
        )
        return (lo, hi)
    raise HTTPException(
        status_code=422,
        detail=f"unknown catalog checkpoint: {label}",
    )


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
    query_text = body.query.strip()
    filters: list[list[object]] = []
    if body.category:
        filters.append(["category", "Eq", body.category])
    drop_window = (
        await checkpoint_window(layer, namespace, body.catalog_run_id)
        if body.catalog_run_id
        else None
    )
    combined_filters = combine_filters(filters)
    if not query_text and not body.catalog_run_id:
        raise HTTPException(
            status_code=422,
            detail="query is required unless catalog_run_id is set",
        )

    if not query_text:
        try:
            browse_filters = [*filters, *temporal_between_filters(drop_window)]
            cursor_id = _drop_browse_cursor_id(body.cursor)
            if cursor_id:
                browse_filters.append(["id", "Gt", cursor_id])
            response = await layer.query_turbopuffer_namespace(
                namespace,
                {
                    "rank_by": ["id", "asc"],
                    "top_k": body.top_k + 1,
                    "include_attributes": body.include_attributes
                    or PRODUCT_INCLUDE_ATTRIBUTES,
                    "filters": combine_filters(browse_filters),
                    "consistency": {"level": "eventual"},
                },
                with_perf=True,
            )
            rows = _query_rows(response.data)
            page_rows = rows[: body.top_k]
        except Exception as exc:
            logger.exception("drop browse failed: namespace=%s", namespace)
            raise HTTPException(
                status_code=502, detail="search upstream failed"
            ) from exc

        return SearchResponse(
            query=body.query,
            namespace=namespace,
            hits=[row_to_hit(row) for row in page_rows],
            stable_as_of=drop_window[1],
            layer_perf=LayerPerf(
                latency_ms=int(response.perf.latency_ms),
                cache_status=response.perf.cache_status,
            ),
            next_cursor=_drop_browse_next_cursor(rows, body.top_k),
            count=None,
        )

    embedder = await get_text_embedder(request.app)
    vector = await asyncio.to_thread(embedder.encode_text, query_text)
    query_kwargs: dict[str, Any] = {
        "vector": vector,
        "top_k": body.top_k,
        "include_attributes": include_attributes,
        "filters": combined_filters,
    }
    if drop_window:
        query_kwargs["between"] = list(drop_window)
    if body.cursor:
        query_kwargs["cursor"] = body.cursor
    try:
        query_task = layer.query_namespace(
            namespace,
            QueryRequest(**query_kwargs),
            **_search_history_kwargs(
                query_text,
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
                    drop_window,
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
    hits = query_hits(response.data)
    return SearchResponse(
        query=body.query,
        namespace=namespace,
        hits=hits,
        stable_as_of=drop_window[1] if drop_window else response.data.stable_as_of,
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
                nearest_to_id=[body.asin],
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

    hits = query_hits(response.data)
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
            include_attributes=PRODUCT_INCLUDE_ATTRIBUTES,
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
        layer_block = _layer_block(metadata)
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


@app.get("/drops", response_model=DropsResponse)
async def drops(
    request: Request,
    namespace: str | None = None,
    limit: int = FastAPIQuery(default=7, ge=1, le=100),
) -> DropsResponse:
    """Recent catalog runs discovered from Layer checkpoint labels."""
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer
    resolved_namespace = namespace or settings.namespace
    try:
        checkpoint_response = await layer.list_checkpoints(
            resolved_namespace,
            limit=limit,
            with_perf=True,
        )
    except Exception as exc:
        logger.exception("drops read failed: namespace=%s", resolved_namespace)
        raise HTTPException(status_code=502, detail="drops upstream failed") from exc

    checkpoints = list(getattr(checkpoint_response.data, "checkpoints", []) or [])
    entries = [
        DropInfo(
            run_id=str(checkpoint.label),
            product_count=int(checkpoint.row_count),
            stable_as_of=int(checkpoint.watermark_ms),
        )
        for checkpoint in checkpoints
    ][:limit]
    return DropsResponse(
        namespace=resolved_namespace,
        drops=entries,
        stable_as_of=entries[0].stable_as_of if entries else None,
        layer_perf=LayerPerf(
            latency_ms=int(checkpoint_response.perf.latency_ms),
            cache_status=checkpoint_response.perf.cache_status,
        ),
    )


@app.get("/search/trending", response_model=TrendingResponse)
async def trending(
    request: Request,
    limit: int = FastAPIQuery(default=12, ge=1, le=50),
) -> TrendingResponse:
    settings = request.app.state.settings
    layer: AsyncHevlayer = request.app.state.layer
    namespace = settings.resolved_trending_namespace
    try:
        response = await layer.query_turbopuffer_namespace(
            namespace,
            {
                "rank_by": ["score", "desc"],
                "top_k": limit,
                "include_attributes": [
                    "query",
                    "count",
                    "score",
                    "ndcg",
                    "sample_top_ids",
                    "as_of",
                ],
            },
            with_perf=True,
        )
    except Exception as exc:
        logger.exception("trending read failed: namespace=%s", namespace)
        raise HTTPException(
            status_code=502, detail="trending upstream failed"
        ) from exc

    entries = [
        TrendingEntry(
            query=str(row["query"]),
            count=_int_value(row.get("count")),
            score=_float_value(row.get("score")),
            ndcg=_float_value(row.get("ndcg")),
            sample_top_ids=_string_list(row.get("sample_top_ids")),
        )
        for row in _query_rows(response.data)
        if isinstance(row.get("query"), str)
    ]
    entries.sort(key=lambda entry: (-entry.score, entry.query))
    return TrendingResponse(
        namespace=namespace,
        mode="quality" if settings.trending_quality_weight > 0 else "frequency",
        entries=entries[:limit],
        stable_as_of=_stable_as_of(response.data),
        layer_perf=LayerPerf(
            latency_ms=int(response.perf.latency_ms),
            cache_status=response.perf.cache_status,
        ),
    )
