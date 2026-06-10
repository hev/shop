"""Internal product data shapes shared across hev-shop services.

The indexer stages product metadata as Layer pipeline chunks, and the
embedding worker turns those chunks into product vectors. HTTP request and
response contracts stay in each service's `models.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
        return attrs


def product_vector_attributes(metadata: dict[str, Any], doc_id: str) -> dict[str, Any]:
    """Build product vector attributes from staged chunk metadata.

    Rating fields are stored as strings to avoid numeric schema conflicts with
    previously indexed rows that used string columns.
    """
    attrs: dict[str, Any] = {"asin": str(metadata.get("asin") or doc_id)}
    for key in ("title", "category", "description", "image_url", "catalog_run_id"):
        value = metadata.get(key)
        if value is not None:
            attrs[key] = str(value)

    if metadata.get("avg_rating") is not None:
        attrs["avg_rating_txt"] = str(metadata["avg_rating"])
    if metadata.get("rating_count") is not None:
        attrs["rating_cnt_txt"] = str(metadata["rating_count"])
    return attrs
