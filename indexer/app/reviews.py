from __future__ import annotations

import hashlib
from typing import Literal


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
