"""Trending reduce worker: aggregate search-history into `<ns>-trending`.

The reduce sibling of `embed.py`. Where the map workers (extract_chunk, embed)
process one document at a time, this is a **reduce**: invoked once per tick, it
reads the whole search-history window for the namespace, scores trending queries
(`hev_shop_common.trending.aggregate_trending`), and upserts one summary row per
query into the materialized `<ns>-trending` namespace, which the storefront then
reads in one cheap, freshness-stamped query.

Declared as the `hev-shop-trending` `Function` in `udfs/trending.yaml`. Two
notes on how it differs from the map workers:

- **Triggering.** The operator is meant to invoke this on a schedule
  (`trigger: schedule`, RFC 0040 §2). That trigger is NOT YET in the Function
  CRD / operator (see `docs/TRENDING_DESIGN.md` → "Layer dependency"). The
  worker logic does not depend on it: `run_trending_once` is a pure tick, and
  `amain` also offers a dev interval loop so it runs today without the trigger.
- **Reads/writes live here, not in the CRD.** Per the CLAUDE.md authoring split
  (operator owns worker shape + triggering; the document lifecycle stays in SDK
  calls), this worker reads `search-history`/`clickstream` and upserts the
  output namespace itself via the injected `AsyncHevlayer`. There is no
  `spec.sources`/`spec.output`. The public client already exposes
  `list_search_history`/`list_clickstream`, so no in-worker `TpufClient` wrap is
  required.

See `docs/TRENDING_DESIGN.md`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import signal
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hevlayer import AsyncHevlayer

from hev_shop_common.config import Settings, get_settings
from hev_shop_common.trending import (
    ClickEvent,
    SearchEvent,
    TrendingConfig,
    TrendingEntry,
    aggregate_trending,
)

logger = logging.getLogger(__name__)


@dataclass
class TrendingContext:
    settings: Settings
    layer: AsyncHevlayer

    @property
    def config(self) -> TrendingConfig:
        return TrendingConfig(
            quality_weight=self.settings.trending_quality_weight,
            min_count=self.settings.trending_min_count,
            top_n=self.settings.trending_top_n,
        )


async def run_trending(ctx: TrendingContext, stop: asyncio.Event) -> None:
    """Dev fallback loop: recompute on an interval until stopped.

    In production the operator invokes `run_trending_once` per scheduled tick
    (no loop). This loop exists so the reduce is runnable before the
    `trigger: schedule` CRD shape lands — and for local iteration.
    """
    while not stop.is_set():
        with suppress(Exception):
            await run_trending_once(ctx)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(
                stop.wait(), ctx.settings.trending_interval_seconds
            )


async def run_trending_once(ctx: TrendingContext) -> int:
    """One reduce tick. Returns the number of trending rows written.

    read window of search-history (+ clickstream in Phase 2) → aggregate →
    upsert `<ns>-trending`. The worker is the only writer of that namespace.
    """
    searches = await _read_search_events(ctx)
    clicks = (
        await _read_click_events(ctx, searches)
        if ctx.settings.trending_quality_weight > 0
        else []
    )
    entries = aggregate_trending(searches, clicks, ctx.config)
    await _write_trending(ctx, entries)
    return len(entries)


async def _read_search_events(ctx: TrendingContext) -> list[SearchEvent]:
    """Read the search-history window via `layer.list_search_history`.

    Restrict to the storefront first-page tag (`settings.trending_history_tag`)
    so bots/pagination don't skew counts, bound by `trending_window_hours`, and
    project each entry to `SearchEvent`.
    """
    from_, to = _window_bounds(ctx)
    response = await ctx.layer.list_search_history(
        ctx.settings.namespace,
        tags=[ctx.settings.trending_history_tag],
        from_=from_,
        to=to,
        limit=500,
    )
    events = _response_items(response, "entries")
    searches: list[SearchEvent] = []
    for event in events:
        raw_query = _field(event, "raw_query")
        if not isinstance(raw_query, str):
            continue
        top_result_ids = _field(event, "top_result_ids") or []
        if not isinstance(top_result_ids, list):
            top_result_ids = []
        trace_id = _field(event, "trace_id")
        searches.append(
            SearchEvent(
                trace_id=trace_id if isinstance(trace_id, str) else "",
                raw_query=raw_query,
                top_result_ids=[str(doc_id) for doc_id in top_result_ids],
                timestamp_ms=_timestamp_ms(event),
            )
        )
    return searches


async def _read_click_events(
    ctx: TrendingContext, searches: list[SearchEvent]
) -> list[ClickEvent]:
    """Read clickstream for the window via `layer.list_clickstream` (Phase 2).

    Joined to searches by `trace_id` for NDCG. Requires the storefront to thread
    the search `traceparent` through to the product fetch (gateway side already
    stamps it — RFC 0040 §4, gap 3 closed).
    """
    if not searches:
        return []
    from_, to = _window_bounds(ctx)
    response = await ctx.layer.list_clickstream(
        ctx.settings.namespace,
        from_=from_,
        to=to,
        limit=500,
    )
    trace_ids = {search.trace_id for search in searches if search.trace_id}
    events = _response_items(response, "events")
    clicks: list[ClickEvent] = []
    for event in events:
        trace_id = _field(event, "trace_id")
        doc_id = _field(event, "doc_id")
        if not isinstance(trace_id, str) or trace_id not in trace_ids:
            continue
        if not isinstance(doc_id, str):
            continue
        clicks.append(
            ClickEvent(
                trace_id=trace_id,
                doc_id=doc_id,
                timestamp_ms=_timestamp_ms(event),
            )
        )
    return clicks


async def _write_trending(ctx: TrendingContext, entries: list[TrendingEntry]) -> None:
    """Upsert one doc per trending query into `<ns>-trending`.

    Each row: {query, count, ndcg, score, sample_top_ids, as_of} plus the
    `_derived_from`/`_derived_by` provenance attributes (RFC 0040 §6). This is a
    plain namespace upsert via the injected client (not a pipeline write).
    """
    if not entries:
        return
    as_of = int(time.time() * 1000)
    rows = [
        {
            "id": _trending_row_id(entry.query),
            "query": entry.query,
            "count": entry.count,
            "score": entry.score,
            "ndcg": entry.ndcg,
            "sample_top_ids": entry.sample_top_ids,
            "as_of": as_of,
            "_derived_from": ctx.settings.namespace,
            "_derived_by": "hev-shop-trending",
        }
        for entry in entries
    ]
    await ctx.layer.write_namespace(
        ctx.settings.resolved_trending_namespace,
        {"upsert_rows": rows},
    )


def _window_bounds(ctx: TrendingContext) -> tuple[str, str]:
    to_dt = datetime.now(UTC)
    from_dt = to_dt - timedelta(hours=ctx.settings.trending_window_hours)
    return _iso_z(from_dt), _iso_z(to_dt)


def _iso_z(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _response_data(response: Any) -> Any:
    return getattr(response, "data", response)


def _response_items(response: Any, field: str) -> list[Any]:
    data = _response_data(response)
    if isinstance(data, list):
        return data
    value = _field(data, field)
    return value if isinstance(value, list) else []


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _timestamp_ms(event: Any) -> int:
    timestamp_ms = _field(event, "timestamp_ms")
    if isinstance(timestamp_ms, int):
        return timestamp_ms
    timestamp_nanos = _field(event, "timestamp_nanos")
    if isinstance(timestamp_nanos, int):
        return timestamp_nanos // 1_000_000
    return 0


def _trending_row_id(query: str) -> str:
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    return f"trend:{digest}"


async def amain() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if udf_id := os.environ.get("HEVLAYER_FUNCTION_ID"):
        logger.info("running as Function %s", udf_id)
    layer = AsyncHevlayer(
        api_key=settings.layer_api_key,
        base_url=settings.layer_gateway_url,
        timeout=settings.http_timeout_seconds,
    )
    ctx = TrendingContext(settings=settings, layer=layer)
    stop = asyncio.Event()
    _install_signals(stop)
    try:
        # Once-per-tick when invoked by the scheduler; the loop is the dev
        # fallback until `trigger: schedule` lands (see module docstring).
        if os.environ.get("TRENDING_RUN_ONCE"):
            await run_trending_once(ctx)
        else:
            await run_trending(ctx, stop)
    finally:
        await layer.aclose()


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


if __name__ == "__main__":
    asyncio.run(amain())
