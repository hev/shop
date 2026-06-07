from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hev_shop_common.records import ProductRecord

if TYPE_CHECKING:
    from hev_shop_common.config import Settings

logger = logging.getLogger("hev_shop.dataset")


def dataset_config(category: str) -> str:
    category = category.strip()
    if category.startswith("raw_meta_"):
        return category
    return f"raw_meta_{category.replace(' ', '_')}"


def dataset_domain(category: str) -> str:
    config = dataset_config(category)
    return config.removeprefix("raw_meta_")


def metadata_url(repo: str, category: str) -> str:
    domain = dataset_domain(category)
    return (
        f"https://huggingface.co/datasets/{repo}/resolve/main/"
        f"raw/meta_categories/meta_{domain}.jsonl"
    )


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

    def iter_products(
        self, *, category: str, offset: int = 0, limit: int = 100
    ) -> Iterator[ProductRecord]:
        self.settings.dataset_cache_dir.mkdir(parents=True, exist_ok=True)
        domain = dataset_domain(category)
        cached_path = self.settings.dataset_cache_dir / f"meta_{domain}.jsonl"
        yielded = 0
        seen_valid = 0

        for row in self._iter_rows(category, cached_path):
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

    def _iter_rows(self, category: str, cached_path: Any) -> Iterator[dict[str, Any]]:
        path = self._ensure_cached(
            cached_path, metadata_url(self.settings.hf_dataset, category)
        )
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                yield json.loads(line)

    def _ensure_cached(self, cached_path: Path, source_url: str) -> Path:
        if cached_path.exists():
            return cached_path

        cached_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cached_path.with_name(
            f".{cached_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        self._download_with_resume(source_url, tmp_path)
        if cached_path.exists():
            tmp_path.unlink(missing_ok=True)
        else:
            tmp_path.replace(cached_path)
        return cached_path

    def _download_with_resume(self, url: str, dest: Path) -> None:
        max_attempts = max(1, getattr(self.settings, "dataset_download_max_attempts", 6))
        backoff_seconds = 5.0
        chunk_size = 1 << 20

        for attempt in range(1, max_attempts + 1):
            offset = dest.stat().st_size if dest.exists() else 0
            request = urllib.request.Request(url)
            if self.settings.hf_token:
                request.add_header("Authorization", f"Bearer {self.settings.hf_token}")
            if offset > 0:
                request.add_header("Range", f"bytes={offset}-")
            mode = "ab" if offset > 0 else "wb"

            try:
                with urllib.request.urlopen(
                    request, timeout=self.settings.http_timeout_seconds
                ) as response:
                    if offset > 0 and response.status not in (206, 200):
                        dest.unlink(missing_ok=True)
                        raise urllib.error.HTTPError(
                            url,
                            response.status,
                            "range not honored",
                            response.headers,
                            None,
                        )
                    with dest.open(mode) as file:
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            file.write(chunk)
                logger.info(
                    "downloaded %s to %s (%d bytes, attempt %d)",
                    url,
                    dest,
                    dest.stat().st_size,
                    attempt,
                )
                return
            except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
                logger.warning(
                    "download %s attempt %d/%d failed at %d bytes: %s",
                    url,
                    attempt,
                    max_attempts,
                    dest.stat().st_size if dest.exists() else 0,
                    err,
                )
                if attempt >= max_attempts:
                    raise
                time.sleep(backoff_seconds * attempt)
