"""Pydantic request/response models for the indexer control plane."""

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
