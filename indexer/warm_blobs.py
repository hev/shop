"""Blob cache-warm worker: hydrate product-image blobs onto the gateway NVMe cache.

RFC 0055 gave product images a durable home in Layer's S3 blob store, referenced
by an `image_blob` string attribute on each row and served pull-through by the
gateway (Aerospike `get_raw` -> miss -> S3 -> `put_raw`). Durability is solved;
what this worker adds is *proactive* warmth: a single `hint_cache_warm?blobs=true`
call that scans the namespace and writes referenced blobs into the NVMe document
cache until a byte budget is hit, so the storefront serves images hot instead of
paying a cold S3 round-trip on first read.

Declared as the `hev-shop-warm-blobs` `Function` in `udfs/warm-blobs.yaml`
(`triggers: [schedule]`, RFC 0040 §2). The schedule matters: the document cache is
`resetOnStart: true` -- wiped on every gateway restart -- so the warm must recur,
not run once. The budget stays conservative (`blob_warm_budget_bytes`, ~22 GiB)
because the 64 GiB cache is shared with the document/vector cache that keeps search
fast; the catalog (~141 GiB of images) cannot fit and its long tail warms on read.

Like `trending.py`, this is a reduce-shaped worker: the gateway does the scan and
the writes, so there is no `spec.sources`/`spec.output` in the CRD. One tick is one
`hint_cache_warm` call (the gateway paginates internally up to the budget). The
worker runs in an operator-owned Deployment, so `amain` defaults to an interval
loop that stays alive for the cron window; set `WARM_RUN_ONCE=1` for a single warm
(manual/local runs and tests), matching `trending.py`'s `TRENDING_RUN_ONCE`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress

from hevlayer import AsyncHevlayer, HintCacheWarmResponse

from hev_shop_common.config import Settings, get_settings

logger = logging.getLogger(__name__)


async def warm_once(layer: AsyncHevlayer, settings: Settings) -> HintCacheWarmResponse:
    """One warm tick: hydrate image blobs onto NVMe up to the byte budget.

    Blobs-only -- documents/snapshots/turbopuffer stay off so the call neither
    re-warms nor evicts the document cache beyond the blob budget. The gateway
    scans pages and stops at `blob_budget_bytes`, so there is no caller loop here.
    """
    response = await layer.hint_cache_warm(
        settings.namespace,
        blobs=True,
        blob_budget_bytes=settings.blob_warm_budget_bytes,
        page_size=settings.blob_warm_page_size,
        documents=False,
        snapshots=False,
        turbopuffer=False,
    )
    _log_result(settings, response)
    return response


def _log_result(settings: Settings, response: HintCacheWarmResponse) -> None:
    blobs = response.blobs
    if blobs is None:
        logger.warning(
            "warm response carried no blobs section for %s", settings.namespace
        )
        return
    logger.info(
        "warmed %s blob objects (%s bytes) from %s docs, %s refs; budget_exhausted=%s",
        blobs.objects,
        blobs.bytes,
        blobs.documents_scanned,
        blobs.refs_seen,
        blobs.budget_exhausted,
    )
    if blobs.missing or blobs.invalid_refs:
        logger.warning(
            "warm saw %s missing and %s invalid blob refs in %s",
            blobs.missing,
            blobs.invalid_refs,
            settings.namespace,
        )
    if blobs.objects == 0:
        logger.warning(
            "warm wrote 0 blobs -- confirm Index.spec.blobs.referenceAttributes "
            "declares the blob attribute for %s",
            settings.namespace,
        )


async def run_loop(
    layer: AsyncHevlayer, settings: Settings, stop: asyncio.Event
) -> None:
    """Dev/window loop: re-warm on an interval until stopped.

    The worker runs in an operator-owned Deployment, so exiting after a single
    warm would just restart-loop. Staying alive and re-warming on an interval
    keeps the pod healthy for its cron window and self-heals the cache; SIGTERM
    (KEDA scale-to-zero at the window's end) stops the loop. `trending.py` uses
    the same pattern.
    """
    while not stop.is_set():
        with suppress(Exception):
            await warm_once(layer, settings)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), settings.blob_warm_interval_seconds)


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


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
    stop = asyncio.Event()
    _install_signals(stop)
    try:
        # Single warm when WARM_RUN_ONCE is set (manual/local/tests); otherwise the
        # interval loop keeps the Deployment pod alive across its cron window.
        if os.environ.get("WARM_RUN_ONCE"):
            await warm_once(layer, settings)
        else:
            await run_loop(layer, settings, stop)
    finally:
        await layer.aclose()


if __name__ == "__main__":
    asyncio.run(amain())
