"""CPU extraction stage: claim an index job, read the source, stage chunks.

Declared as the `extract-chunk` Pipeline resource in `pipelines/`; the Layer
operator runs this script and injects `HEVLAYER_PIPELINE_ID` (the job queue)
and `HEVLAYER_BASE_URL`. Each job document carries the target product
pipeline and namespace in its chunk metadata, staged by `app.py` /index.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from hevlayer import (
    AsyncHevlayer,
    Chunk,
    ClaimDocumentsRequest,
    HeartbeatDocumentsRequest,
    PutChunksRequest,
)

from hev_shop_common.config import Settings, get_settings
from hev_shop_common.records import ProductRecord

from dataset import AmazonProductDataset

logger = logging.getLogger(__name__)


# --- Extraction job shape ---------------------------------------------------

EXTRACTION_JOB_CHUNK_ID = "extraction-job"


@dataclass(frozen=True)
class ExtractionJob:
    id: str
    pipeline_id: str
    namespace: str
    category: str
    row_offset: int
    row_limit: int
    catalog_run_id: str | None = None


def build_index_jobs(
    *,
    pipeline_id: str,
    namespace: str,
    category: str,
    count: int,
    job_size: int,
    catalog_run_id: str | None = None,
) -> list[ExtractionJob]:
    if count == 0:
        return []
    if count < -1:
        raise ValueError("count must be -1 or non-negative")
    if job_size <= 0:
        raise ValueError("job_size must be positive")

    if count == -1:
        return [
            ExtractionJob(
                id=new_extraction_job_id(),
                pipeline_id=pipeline_id,
                namespace=namespace,
                category=category,
                row_offset=0,
                row_limit=-1,
                catalog_run_id=catalog_run_id,
            )
        ]

    jobs: list[ExtractionJob] = []
    offset = 0
    while offset < count:
        limit = min(job_size, count - offset)
        jobs.append(
            ExtractionJob(
                id=new_extraction_job_id(),
                pipeline_id=pipeline_id,
                namespace=namespace,
                category=category,
                row_offset=offset,
                row_limit=limit,
                catalog_run_id=catalog_run_id,
            )
        )
        offset += limit
    return jobs


def new_extraction_job_id() -> str:
    return f"index:{uuid4().hex}"


def extraction_job_metadata(job: ExtractionJob) -> dict[str, Any]:
    metadata = {
        "pipeline_id": job.pipeline_id,
        "namespace": job.namespace,
        "category": job.category,
        "row_offset": job.row_offset,
        "row_limit": job.row_limit,
    }
    if job.catalog_run_id:
        metadata["catalog_run_id"] = job.catalog_run_id
    return metadata


def extraction_job_from_chunks(
    document_id: str, chunks: list[dict[str, Any]]
) -> ExtractionJob:
    if not chunks:
        raise ValueError(f"extraction job {document_id!r} has no chunks")
    metadata = chunks[0].get("metadata") or {}
    return ExtractionJob(
        id=document_id,
        pipeline_id=str(metadata["pipeline_id"]),
        namespace=str(metadata["namespace"]),
        category=str(metadata["category"]),
        row_offset=int(metadata.get("row_offset") or 0),
        row_limit=int(metadata["row_limit"]),
        catalog_run_id=(
            str(metadata["catalog_run_id"])
            if metadata.get("catalog_run_id") is not None
            else None
        ),
    )


# --- Worker -----------------------------------------------------------------


async def stage_product(
    layer: AsyncHevlayer,
    pipeline_id: str,
    product: ProductRecord,
    *,
    catalog_run_id: str | None = None,
) -> None:
    metadata = product.attributes()
    if catalog_run_id:
        metadata["catalog_run_id"] = catalog_run_id
    await layer.put_pipeline_document_chunks(
        pipeline_id,
        product.asin,
        PutChunksRequest(
            chunks=[
                Chunk(
                    id=product.asin,
                    text=product.document_text(),
                    metadata=metadata,
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
                    await stage_product(
                        self.layer,
                        job.pipeline_id,
                        product,
                        catalog_run_id=job.catalog_run_id,
                    )
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


# --- Entrypoint --------------------------------------------------------------


async def amain() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if pipeline_id := os.environ.get("HEVLAYER_PIPELINE_ID"):
        settings.extraction_pipeline_id = pipeline_id
    stop = asyncio.Event()
    _install_signals(stop)
    layer = AsyncHevlayer(
        api_key=settings.layer_api_key,
        base_url=settings.layer_gateway_url,
        timeout=settings.http_timeout_seconds,
    )
    worker = ExtractionWorker(
        settings=settings,
        layer=layer,
        dataset=AmazonProductDataset(settings),
    )
    try:
        await worker.run_forever(stop)
    finally:
        await worker.close()
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
