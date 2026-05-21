"""Pydantic request/response models for the FastAPI surface.

Pure HTTP API contract. Internal data shapes (ProductRecord,
ReviewRecord, vector attribute extractors, review namespace helpers)
live in `records.py`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from hev_shop_common.records import dedupe_categories


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
    pipeline_id: str | None = None
    namespace: str | None = None
    job_size: int | None = None

    def resolved_categories(self, default_category: str) -> list[str]:
        if self.categories is not None:
            categories = self.categories
        else:
            categories = [self.category or default_category]
        return dedupe_categories(categories)


class BackfillRequest(BaseModel):
    category: str = Field(..., description="HF dataset category (e.g., Electronics)")
    asins: list[str] | None = Field(
        default=None,
        description=(
            "Optional explicit ASIN list. When provided, product_limit is "
            "ignored. ASINs must belong to the given category — the HF dataset "
            "is sharded by category, so reviews are looked up in that file."
        ),
    )
    product_limit: int = Field(
        default=1000,
        description=(
            "When asins is omitted, cap how many products to read from the "
            "HF dataset for the category. -1 = unlimited."
        ),
    )
    reviews_per_product: int | None = Field(
        default=None,
        description=(
            "Cap reviews staged per ASIN. Defaults to the server's "
            "REVIEW_RECENT_CAP_PER_PRODUCT setting."
        ),
    )
    max_total_reviews: int | None = Field(
        default=None,
        description="Global cap on reviews staged across the job.",
    )
    stages: list[str] | None = Field(
        default=None,
        description=(
            "Subset of ['embed','classify','aggregate']. Defaults to all "
            "three. 'embed'/'classify' stage review work items; 'aggregate' "
            "re-runs the product-level tag rollup for the affected ASINs."
        ),
    )
    pipeline_id: str | None = Field(
        default=None,
        description="Product pipeline id (defaults to settings.default_pipeline_id).",
    )
    namespace: str | None = Field(
        default=None,
        description="Product namespace (defaults to settings.namespace).",
    )


class BackfillResponse(BaseModel):
    job_id: str
    pipeline_id: str
    namespace: str
    category: str
    asin_count: int | None = None
    product_limit: int
    reviews_per_product: int | None = None
    max_total_reviews: int | None = None
    stages: list[str]


class IndexCategoryResponse(BaseModel):
    category: str
    count: int
    jobs_created: int


class IndexResponse(BaseModel):
    pipeline_id: str
    namespace: str
    category: str
    count: int
    jobs_created: int
    categories: list[IndexCategoryResponse] = Field(default_factory=list)


class StatusResponse(BaseModel):
    pipeline_id: str
    layer: dict[str, Any]
    jobs: dict[str, int]
    extraction: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Free-text search query")
    top_k: int = Field(default=10, ge=1, le=200)
    namespace: str | None = None
    include_attributes: list[str] | None = None
    category: str | None = None
    tags: list[str] | None = None
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
            "If true, fan out an extra /v2/namespaces/{ns}/count call against "
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


class LayerPerf(BaseModel):
    """One Layer gateway round-trip's timing + cache disposition,
    surfaced to the UI so the showcase can render `42ms · cache hit`
    inline. `cache_status` is the gateway's `x-layer-cache` header
    (`"hit"`, `"miss"`, or `"miss-on-error"`); `None` when the gateway
    didn't attach the header — the `query` endpoint doesn't go through
    the document cache, so query perfs always have `cache_status=None`."""

    latency_ms: int
    cache_status: str | None = None


class SearchHit(BaseModel):
    id: str
    dist: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class CountInfo(BaseModel):
    """Result of a /v2/namespaces/{ns}/count fan-out. `bounded=True` means
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


class ReviewSearchResponse(SearchResponse):
    asin: str
    category: str | None = None


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


class ReviewSample(BaseModel):
    review_id: str
    asin: str
    title: str | None = None
    text: str
    rating: int | None = None


class ReviewSamplesResponse(BaseModel):
    asin: str
    samples: list[ReviewSample]


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
            "(not the category scan)."
        ),
    )
