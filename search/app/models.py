"""Pydantic request/response contracts for the read API.

Pure HTTP shapes. Internal data shapes (ProductRecord and vector-attribute
extractors) live in
`hev_shop_common.records`. Indexer-side request shapes (IndexRequest,
StatusResponse) live in `indexer/app/models.py`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LayerPerf(BaseModel):
    """One Layer gateway round-trip's timing + cache disposition,
    surfaced to the UI so the showcase can render `42ms · cache hit`
    inline. `cache_status` is the gateway's `x-layer-cache` header
    (`"hit"`, `"miss"`, or `"miss-on-error"`); `None` when the gateway
    didn't attach the header — the `query` endpoint doesn't go through
    the document cache, so query perfs always have `cache_status=None`."""

    latency_ms: int
    cache_status: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Free-text search query")
    top_k: int = Field(default=10, ge=1, le=200)
    namespace: str | None = None
    include_attributes: list[str] | None = None
    category: str | None = None
    cursor: str | None = Field(
        default=None,
        description=(
            "Opaque pagination cursor from a prior /search response's "
            "next_cursor. Re-send the same query/filters/top_k to keep paging "
            "consistent; the gateway re-applies the consistency watermark."
        ),
    )
    with_count: bool = Field(
        default=False,
        description=(
            "If true, fan out an extra /v2/namespaces/{ns}/result-count call against "
            "the same query vector + filters to estimate how many docs sit "
            "within max_distance. Costs one extra round-trip."
        ),
    )
    max_distance: float = Field(
        default=0.4,
        ge=0.0,
        le=2.0,
        description=(
            "Cosine-distance ceiling for with_count. 0.4 is tight (\"results "
            "worth showing\"); raise toward 1.0 for looser totals."
        ),
    )


class SearchHit(BaseModel):
    id: str
    dist: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class CountInfo(BaseModel):
    """Result of a /v2/namespaces/{ns}/result-count fan-out. `bounded=True` means
    one or more shards saturated their top_k cap on this round, so `count`
    is a lower bound — render it as "≥N" rather than "=N"."""

    count: int
    bounded: bool
    timed_out: bool = False
    shards_saturated: int = 0
    shards_total: int = 0
    max_distance: float
    layer_perf: LayerPerf | None = None


class SearchResponse(BaseModel):
    query: str
    namespace: str
    hits: list[SearchHit]
    stable_as_of: int | None = Field(
        default=None,
        description=(
            "Epoch-ms watermark — results reflect everything indexed at or "
            "before this timestamp. None until the gateway's consistency "
            "watcher has observed a clean snapshot for the namespace."
        ),
    )
    layer_perf: LayerPerf | None = Field(
        default=None,
        description="Gateway round-trip timing for the query call.",
    )
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Opaque cursor for the next page. Present iff the gateway returned "
            "a full top_k (i.e. there may be more results). Pass it back as "
            "`cursor` on the next /search call alongside the same filters."
        ),
    )
    count: CountInfo | None = Field(
        default=None,
        description="Set when the caller requested with_count.",
    )


class RecommendRequest(BaseModel):
    asin: str = Field(..., min_length=1, description="Seed product ASIN")
    top_k: int = Field(default=10, ge=1, le=200)
    namespace: str | None = None
    include_attributes: list[str] | None = None
    category: str | None = None


class RecommendResponse(BaseModel):
    asin: str
    namespace: str
    hits: list[SearchHit]
    stable_as_of: int | None = None
    layer_perf: LayerPerf | None = None
    next_cursor: str | None = None


class ProductResponse(BaseModel):
    asin: str
    namespace: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    layer_perf: LayerPerf | None = Field(
        default=None,
        description=(
            "Gateway round-trip timing for the document fetch. `cache_status` "
            "= 'hit' means Aerospike served the document without touching "
            "turbopuffer."
        ),
    )


class CategoryBucket(BaseModel):
    value: str
    doc_count: int


class MetaResponse(BaseModel):
    namespace: str
    vectors: int
    categories: list[CategoryBucket]
    stable_as_of: int | None = None
    is_stable: bool = False
    layer_perf: LayerPerf | None = Field(
        default=None,
        description=(
            "Gateway round-trip timing for the namespace metadata fetch "
            "(not the category snapshot)."
        ),
    )
