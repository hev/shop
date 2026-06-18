from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

from hev_shop_common.records import ProductRecord
from huggingface_source import (
    HuggingFaceSourceReader,
    dataset_config,
    dataset_domain,
    metadata_url,
)

if TYPE_CHECKING:
    from hev_shop_common.config import Settings


def coerce_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def coerce_int(value: Any) -> int | None:
    if value in (None, "", "None"):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def first_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, Iterable):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return " ".join(parts[:3]) or None
    return str(value).strip() or None


def pick_image_url(images: Any) -> str | None:
    preferred_keys = ("hi_res", "large", "thumb", "url")
    if images is None:
        return None
    if isinstance(images, str):
        return images or None
    if isinstance(images, dict):
        for key in preferred_keys:
            value = images.get(key)
            if isinstance(value, list):
                value = next((item for item in value if item), None)
            if value:
                return str(value)
        return None
    if isinstance(images, Iterable):
        image_items = list(images)
        for key in preferred_keys:
            for image in image_items:
                if isinstance(image, dict):
                    value = image.get(key)
                    if isinstance(value, list):
                        value = next((item for item in value if item), None)
                    if value:
                        return str(value)
        for image in image_items:
            url = pick_image_url(image)
            if url:
                return url
    return None


def product_from_row(row: dict[str, Any], category: str) -> ProductRecord | None:
    asin = first_text(row.get("parent_asin") or row.get("asin"))
    image_url = pick_image_url(row.get("images"))
    if not asin or not image_url:
        return None

    return ProductRecord(
        asin=asin,
        category=category,
        image_url=image_url,
        title=first_text(row.get("title")),
        description=first_text(row.get("description") or row.get("features")),
        price=coerce_float(row.get("price")),
        avg_rating=coerce_float(row.get("average_rating") or row.get("avg_rating")),
        rating_count=coerce_int(row.get("rating_number") or row.get("rating_count")),
    )


class AmazonProductDataset:
    def __init__(self, settings: "Settings") -> None:
        self.settings = settings
        self.reader = HuggingFaceSourceReader(settings)

    def iter_products(
        self, *, category: str, offset: int = 0, limit: int = 100
    ) -> Iterator[ProductRecord]:
        yielded = 0
        seen_valid = 0

        for row in self._iter_rows(category):
            product = product_from_row(row, category)
            if product is None:
                continue
            if seen_valid < max(offset, 0):
                seen_valid += 1
                continue
            yield product
            seen_valid += 1
            yielded += 1
            if limit >= 0 and yielded >= limit:
                break

    def _iter_rows(self, category: str) -> Iterator[dict[str, Any]]:
        yield from self.reader.iter_rows(category)
