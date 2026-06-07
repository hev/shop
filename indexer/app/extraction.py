from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from hevlayer import (
    AsyncHevlayer,
    Chunk,
    ClaimDocumentsRequest,
    CreatePipelineRequest,
    HeartbeatDocumentsRequest,
    PutChunksRequest,
)

from hev_shop_common.config import Settings
from hev_shop_common.records import ProductRecord

from .dataset import AmazonProductDataset
from .jobs import ExtractionJob, extraction_job_from_chunks

logger = logging.getLogger(__name__)


async def stage_product(
    layer: AsyncHevlayer, pipeline_id: str, product: ProductRecord
) -> None:
    await layer.put_pipeline_document_chunks(
        pipeline_id,
        product.asin,
        PutChunksRequest(
            chunks=[
                Chunk(
                    id=product.asin,
                    text=product.document_text(),
                    metadata=product.attributes(),
                )
            ]
        ),
    )


class ExtractionWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        layer: AsyncHevlayer,
        dataset: AmazonProductDataset,
    ) -> None:
        self.settings = settings
        self.layer = layer
        self.dataset = dataset

    async def close(self) -> None:
        return None

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop_event = stop_event or asyncio.Event()
        while not stop_event.is_set():
            task = asyncio.create_task(self.process_once())
            stop_task = asyncio.create_task(stop_event.wait())
            done, _pending = await asyncio.wait(
                {task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if stop_task in done and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                break

            stop_task.cancel()
            with suppress(asyncio.CancelledError):
                await stop_task

            processed = task.result()
            if processed == 0:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self.settings.worker_poll_seconds,
                    )

    async def process_once(self) -> int:
        claim = await self.layer.claim_documents(
            self.settings.extraction_pipeline_id,
            ClaimDocumentsRequest(
                stage="pending",
                limit=1,
                worker_id=self.settings.resolved_worker_id,
                claim_stage="extracting",
                lease_seconds=self.settings.claim_lease_seconds,
            ),
        )
        doc_ids = list(claim.documents)
        if not doc_ids:
            return 0

        doc_id = doc_ids[0]
        chunks = await self.layer.get_pipeline_document_chunks(
            self.settings.extraction_pipeline_id, doc_id
        )
        job = extraction_job_from_chunks(
            doc_id,
            [{"id": c.id, "text": c.text, "metadata": c.metadata} for c in chunks],
        )
        heartbeat = asyncio.create_task(self.heartbeat_job(doc_id))
        try:
            processed = await self.process_job(job)
        except asyncio.CancelledError:
            await self.layer.release_documents(
                self.settings.extraction_pipeline_id,
                [doc_id],
                from_stage="extracting",
                worker_id=self.settings.resolved_worker_id,
            )
            raise
        except Exception:
            logger.exception("extraction job failed", extra={"job_id": job.id})
            await self.layer.fail_documents(
                self.settings.extraction_pipeline_id,
                [doc_id],
                from_stage="extracting",
                worker_id=self.settings.resolved_worker_id,
            )
            return 0
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

        await self.layer.complete_documents(
            self.settings.extraction_pipeline_id,
            [doc_id],
            from_stage="extracting",
            worker_id=self.settings.resolved_worker_id,
        )
        return processed

    async def heartbeat_job(self, document_id: str) -> None:
        while True:
            await asyncio.sleep(self.settings.claim_heartbeat_seconds)
            await self.layer.heartbeat_documents(
                self.settings.extraction_pipeline_id,
                HeartbeatDocumentsRequest(
                    document_ids=[document_id],
                    stage="extracting",
                    worker_id=self.settings.resolved_worker_id,
                ),
            )

    async def process_job(self, job: ExtractionJob) -> int:
        await self.layer.ensure_pipeline(
            CreatePipelineRequest(
                id=job.pipeline_id,
                target_namespace=job.namespace,
                distance_metric=self.settings.distance_metric,
            )
        )
        return await self.process_index_job(job)

    async def process_index_job(self, job: ExtractionJob) -> int:
        products = list(
            self.dataset.iter_products(
                category=job.category, offset=job.row_offset, limit=job.row_limit
            )
        )
        processed = await self.stage_products(job, products)
        logger.info(
            "completed extraction job",
            extra={
                "job_id": job.id,
                "processed_count": processed,
            },
        )
        if processed == 0:
            raise RuntimeError("extraction job did not stage any products")
        return processed

    async def stage_products(
        self, job: ExtractionJob, products: list[ProductRecord]
    ) -> int:
        if not products:
            return 0

        queue: asyncio.Queue[ProductRecord] = asyncio.Queue()
        for product in products:
            queue.put_nowait(product)

        async def worker() -> int:
            processed = 0
            while True:
                try:
                    product = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    await stage_product(self.layer, job.pipeline_id, product)
                    processed += 1
                except Exception:
                    logger.exception(
                        "failed to stage product",
                        extra={"asin": product.asin, "pipeline_id": job.pipeline_id},
                    )
                finally:
                    queue.task_done()
            return processed

        concurrency = max(
            1, min(self.settings.extraction_concurrency, len(products))
        )
        logger.info(
            "staging %s products with concurrency %s",
            len(products),
            concurrency,
            extra={"job_id": job.id, "category": job.category},
        )
        results = await asyncio.gather(*(worker() for _ in range(concurrency)))
        return sum(results)
