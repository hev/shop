"""Pydantic request/response models for the FastAPI surface.

Pure HTTP API contract. Internal data shapes (ProductRecord,
ReviewRecord, vector attribute extractors, review namespace helpers)
live in `records.py`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .records import dedupe_categories


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
    job_id: int
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


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Free-text search query")
    top_k: int = Field(default=10, ge=1, le=200)
    namespace: str | None = None
    include_attributes: list[str] | None = None
    category: str | None = None
    tags: list[str] | None = None


class SearchHit(BaseModel):
    id: str
    dist: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


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


class ReviewSearchResponse(SearchResponse):
    asin: str
    category: str | None = None


class ProductResponse(BaseModel):
    asin: str
    namespace: str
    attributes: dict[str, Any] = Field(default_factory=dict)


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
