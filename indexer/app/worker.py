from __future__ import annotations

import asyncio
import logging
import signal

from .config import get_settings
from .dataset import AmazonProductDataset
from .extraction import ExtractionWorker
from .layer_client import LayerClient
from .pipeline import STAGES, StageContext, run_stage


# WORKER_TYPE env values map directly to STAGES keys, except "cpu" which
# runs the extraction worker (postgres job queue, not a layer pipeline).
STAGE_FOR_WORKER_TYPE = {
    "gpu": "embed-products",
    "review-embed": "embed-reviews",
    "review-classify": "classify-reviews",
    "review-aggregate": "aggregate-tags",
}


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
    layer = LayerClient(
        settings.layer_gateway_url,
        settings.http_timeout_seconds,
        api_key=settings.layer_api_key,
    )

    try:
        if settings.worker_type == "cpu":
            await layer.create_pipeline(
                settings.extraction_pipeline_id,
                settings.namespace,
                settings.distance_metric,
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
        elif settings.worker_type in STAGE_FOR_WORKER_TYPE:
            stage = STAGES[STAGE_FOR_WORKER_TYPE[settings.worker_type]]
            ctx = StageContext(settings=settings, layer=layer)
            try:
                await run_stage(stage, ctx, stop_event)
            finally:
                # OpenRouterReviewClassifier holds an httpx client; close
                # it if classify-reviews lazily instantiated one.
                classifier = ctx._classifier
                if classifier is not None and hasattr(classifier, "close"):
                    await classifier.close()
        else:
            raise ValueError(
                "WORKER_TYPE must be one of 'cpu', "
                + ", ".join(repr(name) for name in STAGE_FOR_WORKER_TYPE)
            )
    finally:
        await layer.close()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
