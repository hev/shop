from __future__ import annotations

import heapq
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hev_shop_common.records import ProductRecord, ReviewRecord

if TYPE_CHECKING:
    from hev_shop_common.config import Settings

logger = logging.getLogger("hev_shop.dataset")


def dataset_config(category: str) -> str:
    category = category.strip()
    if category.startswith("raw_meta_"):
        return category
    return f"raw_meta_{category.replace(' ', '_')}"


def review_dataset_config(category: str) -> str:
    category = category.strip()
    if category.startswith("raw_review_"):
        return category
    return f"raw_review_{category.replace(' ', '_')}"


def dataset_domain(category: str) -> str:
    config = dataset_config(category)
    return config.removeprefix("raw_meta_")


def review_dataset_domain(category: str) -> str:
    config = review_dataset_config(category)
    return config.removeprefix("raw_review_")


def metadata_url(repo: str, category: str) -> str:
    domain = dataset_domain(category)
    return (
        f"https://huggingface.co/datasets/{repo}/resolve/main/"
        f"raw/meta_categories/meta_{domain}.jsonl"
    )


def reviews_url(repo: str, category: str) -> str:
    domain = review_dataset_domain(category)
    return (
        f"https://huggingface.co/datasets/{repo}/resolve/main/"
        f"raw/review_categories/{domain}.jsonl"
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


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return False


def coerce_datetime(value: Any) -> datetime | None:
    if value in (None, "", "None"):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and value.strip().lstrip("-").isdigit()
    ):
        raw = float(value)
        if abs(raw) > 10_000_000_000:
            raw /= 1000
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
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


def stable_review_id(row: dict[str, Any], asin: str) -> str:
    explicit = first_text(row.get("review_id") or row.get("id"))
    if explicit:
        return explicit
    key_parts = [
        asin,
        first_text(row.get("user_id")) or "",
        str(row.get("timestamp") or ""),
        first_text(row.get("title")) or "",
        first_text(row.get("text")) or "",
    ]
    digest = hashlib.sha1("\n".join(key_parts).encode("utf-8")).hexdigest()
    return digest[:24]


def review_from_row(row: dict[str, Any], category: str) -> ReviewRecord | None:
    asin = first_text(row.get("parent_asin") or row.get("asin"))
    text = first_text(row.get("text"))
    if not asin or not text:
        return None

    rating = coerce_int(row.get("rating"))
    return ReviewRecord(
        asin=asin,
        review_id=stable_review_id(row, asin),
        category=category,
        rating=rating,
        title=first_text(row.get("title")),
        text=text,
        helpful_vote=coerce_int(row.get("helpful_vote")) or 0,
        verified_purchase=coerce_bool(row.get("verified_purchase")),
        timestamp=coerce_datetime(row.get("timestamp")),
    )


def review_timestamp_sort_value(review: ReviewRecord) -> float:
    if review.timestamp is None:
        return 0.0
    return review.timestamp.timestamp()


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

    def iter_reviews(
        self, *, category: str, offset: int = 0, limit: int = 100
    ) -> Iterator[ReviewRecord]:
        self.settings.dataset_cache_dir.mkdir(parents=True, exist_ok=True)
        domain = review_dataset_domain(category)
        cached_path = self.settings.dataset_cache_dir / f"reviews_{domain}.jsonl"
        yielded = 0
        seen_valid = 0

        for row in self._iter_review_rows(category, cached_path):
            review = review_from_row(row, category)
            if review is None:
                continue
            if seen_valid < max(offset, 0):
                seen_valid += 1
                continue
            yield review
            seen_valid += 1
            yielded += 1
            if limit >= 0 and yielded >= limit:
                break

    def iter_reviews_for_asins(
        self,
        *,
        category: str,
        asins: set[str],
        recent_limit: int,
        helpful_limit: int,
    ) -> Iterator[ReviewRecord]:
        if not asins:
            return iter(())

        self.settings.dataset_cache_dir.mkdir(parents=True, exist_ok=True)
        domain = review_dataset_domain(category)
        cached_path = self.settings.dataset_cache_dir / f"reviews_{domain}.jsonl"
        recent: dict[str, list[tuple[float, int, ReviewRecord]]] = {
            asin: [] for asin in asins
        }
        helpful: dict[str, list[tuple[int, float, int, ReviewRecord]]] = {
            asin: [] for asin in asins
        }
        sequence = 0

        for row in self._iter_review_rows(category, cached_path):
            review = review_from_row(row, category)
            if review is None or review.asin not in asins:
                continue
            sequence += 1
            if recent_limit > 0:
                recent_heap = recent[review.asin]
                item = (review_timestamp_sort_value(review), sequence, review)
                if len(recent_heap) < recent_limit:
                    heapq.heappush(recent_heap, item)
                elif item > recent_heap[0]:
                    heapq.heapreplace(recent_heap, item)
            if helpful_limit > 0:
                helpful_heap = helpful[review.asin]
                item = (
                    review.helpful_vote,
                    review_timestamp_sort_value(review),
                    sequence,
                    review,
                )
                if len(helpful_heap) < helpful_limit:
                    heapq.heappush(helpful_heap, item)
                elif item > helpful_heap[0]:
                    heapq.heapreplace(helpful_heap, item)

        selected: dict[str, ReviewRecord] = {}
        for heap in recent.values():
            for _ts, _sequence, review in heap:
                selected[review.review_id] = review
        for heap in helpful.values():
            for _helpful, _ts, _sequence, review in heap:
                selected[review.review_id] = review

        ordered = sorted(
            selected.values(),
            key=lambda review: (
                review.asin,
                -review_timestamp_sort_value(review),
                -review.helpful_vote,
                review.review_id,
            ),
        )
        return iter(ordered)

    def _iter_rows(self, category: str, cached_path: Any) -> Iterator[dict[str, Any]]:
        path = self._ensure_cached(
            cached_path, metadata_url(self.settings.hf_dataset, category)
        )
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                yield json.loads(line)

    def _iter_review_rows(
        self, category: str, cached_path: Any
    ) -> Iterator[dict[str, Any]]:
        path = self._ensure_cached(
            cached_path, reviews_url(self.settings.hf_dataset, category)
        )
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                yield json.loads(line)

    # ------------------------------------------------------------------
    # Two-stage extraction: download HF JSONL to /data/dataset once
    # (resumable, with retry), then every backfill reads from local disk.
    # Eliminates the mid-stream JSON-decode crashes that happen when the
    # urllib stream of a multi-GB file is truncated, and turns repeated
    # backfills into local disk reads.
    # ------------------------------------------------------------------

    def _ensure_cached(self, cached_path: Path, source_url: str) -> Path:
        if cached_path.exists():
            return cached_path

        cached_path.parent.mkdir(parents=True, exist_ok=True)
        # Per-process tmp keeps concurrent workers from clobbering each other;
        # the final replace() is atomic on POSIX.
        tmp_path = cached_path.with_name(f".{cached_path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        self._download_with_resume(source_url, tmp_path)
        # Another worker may have promoted its tmp first — keep theirs.
        if cached_path.exists():
            tmp_path.unlink(missing_ok=True)
        else:
            tmp_path.replace(cached_path)
        return cached_path

    def _download_with_resume(self, url: str, dest: Path) -> None:
        """Download `url` to `dest`, resuming via HTTP Range on retry.

        HF sometimes drops long-running connections, which previously
        manifested as JSONDecodeError on a truncated line. Resuming
        avoids re-downloading gigabytes after a hiccup.
        """
        max_attempts = max(1, getattr(self.settings, "dataset_download_max_attempts", 6))
        backoff_seconds = 5.0
        chunk_size = 1 << 20  # 1 MiB

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
                        # Server rejected resume — start over.
                        dest.unlink(missing_ok=True)
                        raise urllib.error.HTTPError(
                            url, response.status, "range not honored", response.headers, None
                        )
                    with dest.open(mode) as file:
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            file.write(chunk)
                logger.info(
                    "downloaded %s to %s (%d bytes, attempt %d)",
                    url, dest, dest.stat().st_size, attempt,
                )
                return
            except (
                urllib.error.URLError,
                ConnectionError,
                TimeoutError,
            ) as err:
                logger.warning(
                    "download %s attempt %d/%d failed at %d bytes: %s",
                    url, attempt, max_attempts,
                    dest.stat().st_size if dest.exists() else 0, err,
                )
                if attempt >= max_attempts:
                    raise
                time.sleep(backoff_seconds * attempt)
