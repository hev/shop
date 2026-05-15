from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .reviews import REVIEW_TAGS


def dedupe_categories(categories: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for category in categories:
        name = category.strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        cleaned.append(name)
        seen.add(key)
    return cleaned


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


@dataclass(frozen=True)
class ProductRecord:
    asin: str
    category: str
    image_url: str
    title: str | None = None
    description: str | None = None
    price: float | None = None
    avg_rating: float | None = None
    rating_count: int | None = None
    image_path: Path | None = None

    def with_image_path(self, image_path: Path) -> "ProductRecord":
        return replace(self, image_path=image_path)

    def document_text(self) -> str:
        parts = [self.title, self.description]
        return "\n".join(part for part in parts if part)

    def attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "asin": self.asin,
            "category": self.category,
            "image_url": self.image_url,
        }
        if self.title:
            attrs["title"] = self.title
        if self.description:
            attrs["description"] = self.description
        if self.price is not None:
            attrs["price"] = self.price
        if self.avg_rating is not None:
            attrs["avg_rating"] = self.avg_rating
        if self.rating_count is not None:
            attrs["rating_count"] = self.rating_count
        if self.image_path is not None:
            attrs["image_path"] = str(self.image_path)
        return attrs


@dataclass(frozen=True)
class ReviewRecord:
    asin: str
    review_id: str
    category: str
    rating: int | None
    title: str | None
    text: str
    helpful_vote: int
    verified_purchase: bool
    timestamp: datetime | None

    def document_text(self) -> str:
        parts = [self.title, self.text]
        return "\n".join(part for part in parts if part)

    def timestamp_iso(self) -> str | None:
        if self.timestamp is None:
            return None
        value = self.timestamp
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    def attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "asin": self.asin,
            "review_id": self.review_id,
            "category": self.category,
            "helpful_vote": self.helpful_vote,
            "verified_purchase": self.verified_purchase,
        }
        if self.rating is not None:
            attrs["rating"] = self.rating
        if self.title:
            attrs["title"] = self.title
        timestamp = self.timestamp_iso()
        if timestamp is not None:
            attrs["timestamp"] = timestamp
        return attrs


def normalize_review_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    allowed = set(REVIEW_TAGS)
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        cleaned = tag.strip()
        if cleaned not in allowed or cleaned in seen:
            continue
        out.append(cleaned)
        seen.add(cleaned)
    return out
