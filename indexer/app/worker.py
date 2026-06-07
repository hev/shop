from __future__ import annotations

import asyncio
import logging
import signal

from hevlayer import AsyncHevlayer, CreatePipelineRequest

from hev_shop_common.config import get_settings

from .dataset import AmazonProductDataset
from .extraction import ExtractionWorker
from .pipeline import StageContext, run_embed_products


# WORKER_TYPE=cpu claims extraction jobs and stages product chunks.
# WORKER_TYPE=gpu claims pending product docs and writes vectors.
WORKER_TYPES = {"cpu", "gpu"}


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: loop.call_soon_threadsafe(stop_event.set))


async def amain() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    layer = AsyncHevlayer(
        api_key=settings.layer_api_key,
        base_url=settings.layer_gateway_url,
        timeout=settings.http_timeout_seconds,
    )

    try:
        if settings.worker_type == "cpu":
            await layer.ensure_pipeline(
                CreatePipelineRequest(
                    id=settings.extraction_pipeline_id,
                    target_namespace=settings.namespace,
                    distance_metric=settings.distance_metric,
                )
            )
            worker = ExtractionWorker(
                settings=settings,
                layer=layer,
                dataset=AmazonProductDataset(settings),
            )
            try:
                await worker.run_forever(stop_event)
            finally:
                await worker.close()
        elif settings.worker_type == "gpu":
            ctx = StageContext(settings=settings, layer=layer)
            await run_embed_products(ctx, stop_event)
        else:
            raise ValueError(
                "WORKER_TYPE must be one of "
                + ", ".join(repr(name) for name in sorted(WORKER_TYPES))
            )
    finally:
        await layer.aclose()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
