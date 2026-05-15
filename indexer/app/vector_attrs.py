from __future__ import annotations

from typing import Any


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


def vector_attributes(metadata: dict[str, Any], doc_id: str) -> dict[str, Any]:
    return product_vector_attributes(metadata, doc_id)
