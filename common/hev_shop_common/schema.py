"""Shared Layer namespace schema declarations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


AMAZON_PRODUCTS_NAMESPACE_SCHEMA: dict[str, Any] = {
    "asin": {"type": "string", "filterable": False},
    "title": {"type": "string", "filterable": False, "full_text_search": True},
    "category": {"type": "string", "filterable": True},
    "description": {"type": "string", "filterable": False},
    "image_url": {"type": "string", "filterable": False},
    "image_blob": {"type": "string", "filterable": False},
    "avg_rating_txt": {"type": "string", "filterable": False},
    "rating_cnt_txt": {"type": "string", "filterable": False},
}


def amazon_products_namespace_schema() -> dict[str, Any]:
    return deepcopy(AMAZON_PRODUCTS_NAMESPACE_SCHEMA)
