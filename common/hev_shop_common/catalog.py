"""Catalog drop label helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def default_catalog_run_id(now: datetime | None = None) -> str:
    at = now or datetime.now(timezone.utc)
    return f"catalog-{at.date().isoformat()}"
