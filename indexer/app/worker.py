from __future__ import annotations

import asyncio
import logging
import signal

from .config import get_settings
from .database import Database
from .dataset import AmazonProductDataset
from .embedding import (
    CLIPImageEmbedder,
    EmbeddingWorker,
    QwenTextEmbedder,
    ReviewEmbeddingWorker,
)
from .extraction import ExtractionWorker
from .layer_client import LayerClient
from .classifier import OpenRouterReviewClassifier
from .review_workers import ReviewAggregateWorker, ReviewClassifierWorker


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
    database = await Database.connect(settings.layer_database_url)
    await database.ensure_schema()
    layer = LayerClient(settings.layer_gateway_url, settings.http_timeout_seconds)

    try:
        if settings.worker_type == "cpu":
            worker = ExtractionWorker(
                settings=settings,
                database=database,
                layer=layer,
                dataset=AmazonProductDataset(settings),
            )
            try:
                await worker.run_forever(stop_event)
            finally:
                await worker.close()
        elif settings.worker_type == "gpu":
            worker = EmbeddingWorker(
                settings=settings,
                database=database,
                layer=layer,
                embedder=CLIPImageEmbedder(settings),
                pipeline_id=settings.default_pipeline_id,
                namespace_resolver=lambda _metadata, _doc_id: settings.namespace,
                include_review_tag_attrs=True,
            )
            await worker.run_forever(stop_event)
        elif settings.worker_type == "review-embed":
            worker = ReviewEmbeddingWorker(
                settings=settings,
                database=database,
                layer=layer,
                embedder=QwenTextEmbedder(settings),
            )
            await worker.run_forever(stop_event)
        elif settings.worker_type == "review-classify":
            worker = ReviewClassifierWorker(
                settings=settings,
                database=database,
                layer=layer,
                classifier=OpenRouterReviewClassifier(settings),
            )
            try:
                await worker.run_forever(stop_event)
            finally:
                await worker.close()
        elif settings.worker_type == "review-aggregate":
            worker = ReviewAggregateWorker(
                settings=settings,
                database=database,
                layer=layer,
            )
            await worker.run_forever(stop_event)
        else:
            raise ValueError(
                "WORKER_TYPE must be one of 'cpu', 'gpu', 'review-embed', "
                "'review-classify', or 'review-aggregate'"
            )
    finally:
        await layer.close()
        await database.close()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
