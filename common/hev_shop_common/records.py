"""Internal data shapes shared across the pipeline.

Three things live here:

1. Product / review dataclasses — the in-memory shape produced by the
   HF dataset reader and consumed by the layer staging calls.
2. Vector-attribute extractors — turn a chunk's metadata into the
   attribute dict turbopuffer wants on each upserted vector / patch.
3. Review-pipeline plumbing — the tag enum, the doc-id prefix scheme
   that segments the reviews pipeline into embed vs. classify work,
   and the namespace-shard helper.

The Pydantic HTTP API contracts (IndexRequest / SearchResponse / …)
stay in `models.py`; those are the API boundary, not data shapes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Review pipeline: tag enum, prefixes, shard helper
# ---------------------------------------------------------------------------


REVIEW_TAGS: tuple[str, ...] = (
    "Buy it for life, no regrets",
    "Falls apart fast",
    "Value Leader",
    "Overpriced",
    "Worth the splurge",
    "Good but...",
    "Setup nightmare",
    "Wish I'd bought sooner",
    "Better in person",
    "Photos misleading",
    "Beginner friendly",
)

REVIEW_EMBED_PREFIX = "review-embed:"
REVIEW_CLASSIFY_PREFIX = "review-classify:"
REVIEW_RAW_CHUNK_PREFIX = "review-raw:"

ReviewWorkKind = Literal["embed", "classify"]


def stable_shard(value: str, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def review_namespace_for(
    asin: str, *, namespace_base: str, shard_count: int
) -> str:
    return f"{namespace_base}-{stable_shard(asin, shard_count)}"


def namespace_for(
    asin: str,
    kind: Literal["product", "review"],
    *,
    product_namespace: str,
    review_namespace_base: str,
    review_shard_count: int,
) -> str:
    if kind == "product":
        return product_namespace
    return review_namespace_for(
        asin, namespace_base=review_namespace_base, shard_count=review_shard_count
    )


def review_work_document_id(kind: ReviewWorkKind, review_id: str) -> str:
    prefix = REVIEW_EMBED_PREFIX if kind == "embed" else REVIEW_CLASSIFY_PREFIX
    return f"{prefix}{review_id}"


def review_raw_chunk_id(review_id: str) -> str:
    return f"{REVIEW_RAW_CHUNK_PREFIX}{review_id}"


def review_id_from_work_document(document_id: str) -> str:
    for prefix in (REVIEW_EMBED_PREFIX, REVIEW_CLASSIFY_PREFIX):
        if document_id.startswith(prefix):
            return document_id[len(prefix) :]
    return document_id


# ---------------------------------------------------------------------------
# Input normalizers (used by both API models and worker code)
# ---------------------------------------------------------------------------


BACKFILL_STAGES = ("embed", "classify", "aggregate")


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


def normalize_backfill_stages(stages: list[str] | None) -> list[str]:
    if stages is None:
        return list(BACKFILL_STAGES)
    allowed = set(BACKFILL_STAGES)
    seen: set[str] = set()
    out: list[str] = []
    for stage in stages:
        cleaned = stage.strip()
        if cleaned not in allowed or cleaned in seen:
            continue
        out.append(cleaned)
        seen.add(cleaned)
    return out


def normalize_asin_list(asins: list[str] | None) -> list[str] | None:
    if asins is None:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for asin in asins:
        cleaned = asin.strip()
        if not cleaned or cleaned in seen:
            continue
        out.append(cleaned)
        seen.add(cleaned)
    return out


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


# ---------------------------------------------------------------------------
# Records: in-memory shapes produced by the dataset reader, consumed by
# the layer staging calls.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Vector attribute extractors — chunk metadata → attribute dict for the
# turbopuffer upsert / patch payload. Product attributes also include a
# few coerced-to-string fields to dodge numeric-schema conflicts on the
# avg_rating / rating_count columns.
# ---------------------------------------------------------------------------


def product_vector_attributes(metadata: dict[str, Any], doc_id: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {"asin": str(metadata.get("asin") or doc_id)}
    for key in ("title", "category", "description", "image_url", "image_path"):
        value = metadata.get(key)
        if value is not None:
            attrs[key] = str(value)

    if metadata.get("avg_rating") is not None:
        attrs["avg_rating_txt"] = str(metadata["avg_rating"])
    if metadata.get("rating_count") is not None:
        attrs["rating_cnt_txt"] = str(metadata["rating_count"])
    return attrs


def review_vector_attributes(
    metadata: dict[str, Any],
    doc_id: str,
    *,
    chunk_idx: int,
    text_chunk: str,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "asin": str(metadata["asin"]),
        "review_id": str(metadata.get("review_id") or doc_id),
        "chunk_idx": chunk_idx,
        "text_chunk": text_chunk,
    }
    for key in ("category", "title", "timestamp"):
        value = metadata.get(key)
        if value is not None:
            attrs[key] = str(value)
    for key in ("rating", "helpful_vote"):
        value = metadata.get(key)
        if value is not None:
            attrs[key] = int(value)
    verified = metadata.get("verified_purchase")
    if verified is not None:
        attrs["verified_purchase"] = bool(verified)
    return attrs
