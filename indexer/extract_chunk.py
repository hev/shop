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
from urllib.parse import quote, unquote
from uuid import uuid4

from hevlayer import (
    AsyncHevlayer,
    Chunk,
    ClaimDocumentsRequest,
    CreatePipelineRequest,
    HeartbeatDocumentsRequest,
    HevlayerError,
    PutChunksRequest,
    SetDocumentsStageRequest,
)

from hev_shop_common.catalog import default_catalog_run_id
from hev_shop_common.config import Settings, get_settings
from hev_shop_common.records import ProductRecord
from hev_shop_common.schema import amazon_products_namespace_schema

from dataset import AmazonProductDataset

logger = logging.getLogger(__name__)


# --- Extraction job shape ---------------------------------------------------

EXTRACTION_JOB_CHUNK_ID = "extraction-job"
REFRESH_DOCUMENT_PREFIX = "refresh:"
SCHEDULED_JOB_PREFIX = "index:scheduled:"


@dataclass(frozen=True)
class ExtractionJob:
    id: str
    pipeline_id: str
    namespace: str
    category: str
    row_offset: int
    row_limit: int
    skip_existing: bool = False


def build_index_jobs(
    *,
    pipeline_id: str,
    namespace: str,
    category: str,
    count: int,
    job_size: int,
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
            )
        )
        offset += limit
    return jobs


def build_scheduled_index_jobs(
    *,
    pipeline_id: str,
    namespace: str,
    category: str,
    catalog_run_id: str,
    row_offset: int,
    count: int,
    job_size: int,
) -> list[ExtractionJob]:
    if count == 0:
        return []
    if count < -1:
        raise ValueError("count must be -1 or non-negative")
    if job_size <= 0:
        raise ValueError("job_size must be positive")
    if row_offset < 0:
        raise ValueError("row_offset must be non-negative")

    if count == -1:
        return [
            scheduled_extraction_job(
                pipeline_id=pipeline_id,
                namespace=namespace,
                category=category,
                catalog_run_id=catalog_run_id,
                row_offset=row_offset,
                row_limit=-1,
            )
        ]

    jobs: list[ExtractionJob] = []
    offset = row_offset
    remaining = count
    while remaining > 0:
        limit = min(job_size, remaining)
        jobs.append(
            scheduled_extraction_job(
                pipeline_id=pipeline_id,
                namespace=namespace,
                category=category,
                catalog_run_id=catalog_run_id,
                row_offset=offset,
                row_limit=limit,
            )
        )
        offset += limit
        remaining -= limit
    return jobs


def new_extraction_job_id() -> str:
    return f"index:{uuid4().hex}"


def refresh_document_id(catalog_run_id: str) -> str:
    return f"{REFRESH_DOCUMENT_PREFIX}{quote(catalog_run_id, safe='')}"


def catalog_run_id_from_refresh_document(document_id: str) -> str | None:
    if not document_id.startswith(REFRESH_DOCUMENT_PREFIX):
        return None
    return unquote(document_id[len(REFRESH_DOCUMENT_PREFIX) :])


def scheduled_extraction_job(
    *,
    pipeline_id: str,
    namespace: str,
    category: str,
    catalog_run_id: str,
    row_offset: int,
    row_limit: int,
) -> ExtractionJob:
    category_token = quote(category, safe="")
    run_token = quote(catalog_run_id, safe="")
    job_id = f"{SCHEDULED_JOB_PREFIX}{run_token}:{category_token}:{row_offset}:{row_limit}"
    return ExtractionJob(
        id=job_id,
        pipeline_id=pipeline_id,
        namespace=namespace,
        category=category,
        row_offset=row_offset,
        row_limit=row_limit,
        skip_existing=True,
    )


def extraction_job_from_document_id(
    document_id: str, *, pipeline_id: str, namespace: str
) -> ExtractionJob | None:
    if not document_id.startswith(SCHEDULED_JOB_PREFIX):
        return None
    parts = document_id.split(":", 5)
    if len(parts) != 6:
        raise ValueError(f"invalid scheduled extraction job id {document_id!r}")
    _, kind, _catalog_run_id, category, row_offset, row_limit = parts
    if kind != "scheduled":
        raise ValueError(f"invalid scheduled extraction job id {document_id!r}")
    return ExtractionJob(
        id=document_id,
        pipeline_id=pipeline_id,
        namespace=namespace,
        category=unquote(category),
        row_offset=int(row_offset),
        row_limit=int(row_limit),
        skip_existing=True,
    )


def extraction_job_metadata(job: ExtractionJob) -> dict[str, Any]:
    metadata = {
        "pipeline_id": job.pipeline_id,
        "namespace": job.namespace,
        "category": job.category,
        "row_offset": job.row_offset,
        "row_limit": job.row_limit,
    }
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
    )


# --- Worker -----------------------------------------------------------------


async def stage_product(
    layer: AsyncHevlayer,
    pipeline_id: str,
    namespace: str,
    product: ProductRecord,
    *,
    skip_existing: bool = False,
) -> bool:
    if skip_existing and await product_exists(layer, namespace, product.asin):
        logger.info("skipping already indexed product", extra={"asin": product.asin})
        return False

    metadata = product.attributes()
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
    return True


async def product_exists(
    layer: AsyncHevlayer, namespace: str, doc_id: str
) -> bool:
    try:
        await layer.fetch_document(namespace, doc_id, include_attributes=[])
    except HevlayerError as exc:
        if exc.status_code == 404:
            return False
        raise
    return True


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
        self._seeded_refresh_labels: set[str] = set()
        self._enqueued_refresh_labels: set[str] = set()

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
        if self.settings.scheduled_pipeline:
            await self.seed_scheduled_refresh()

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
        job_id_for_log = doc_id
        heartbeat = asyncio.create_task(self.heartbeat_job(doc_id))
        try:
            catalog_run_id = catalog_run_id_from_refresh_document(doc_id)
            if catalog_run_id is not None:
                activated = await self.process_refresh_control(catalog_run_id)
                if activated:
                    await self.layer.complete_documents(
                        self.settings.extraction_pipeline_id,
                        [doc_id],
                        from_stage="extracting",
                        worker_id=self.settings.resolved_worker_id,
                    )
                else:
                    await self.layer.release_documents(
                        self.settings.extraction_pipeline_id,
                        [doc_id],
                        from_stage="extracting",
                        worker_id=self.settings.resolved_worker_id,
                    )
                return 0

            chunks = await self.layer.get_pipeline_document_chunks(
                self.settings.extraction_pipeline_id, doc_id
            )
            chunk_dicts = [
                {"id": c.id, "text": c.text, "metadata": c.metadata} for c in chunks
            ]
            if chunk_dicts:
                job = extraction_job_from_chunks(doc_id, chunk_dicts)
            else:
                job = extraction_job_from_document_id(
                    doc_id,
                    pipeline_id=self.settings.default_pipeline_id,
                    namespace=self.settings.namespace,
                )
                if job is None:
                    raise ValueError(f"extraction job {doc_id!r} has no chunks")
            job_id_for_log = job.id
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
            logger.exception("extraction job failed", extra={"job_id": job_id_for_log})
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

    async def seed_scheduled_refresh(self) -> None:
        catalog_run_id = default_catalog_run_id()
        if catalog_run_id in self._seeded_refresh_labels:
            return
        if await self.checkpoint_exists(catalog_run_id):
            self._seeded_refresh_labels.add(catalog_run_id)
            return

        await self.ensure_indexing_targets()
        response = await self.layer.set_documents_stage(
            self.settings.extraction_pipeline_id,
            SetDocumentsStageRequest(
                document_ids=[refresh_document_id(catalog_run_id)],
                stage="pending",
                create_missing=True,
            ),
        )
        self._seeded_refresh_labels.add(catalog_run_id)
        logger.info(
            "seeded scheduled refresh control document",
            extra={
                "catalog_run_id": catalog_run_id,
                "created_count": response.updated,
            },
        )

    async def checkpoint_exists(self, catalog_run_id: str) -> bool:
        try:
            await self.layer.get_checkpoint(self.settings.namespace, catalog_run_id)
        except HevlayerError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True

    async def ensure_indexing_targets(self) -> None:
        await self.layer.ensure_pipeline(
            CreatePipelineRequest(
                id=self.settings.default_pipeline_id,
                target_namespace=self.settings.namespace,
                distance_metric=self.settings.distance_metric,
            )
        )
        await self.layer.update_turbopuffer_namespace_schema(
            self.settings.namespace,
            amazon_products_namespace_schema(),
        )
        await self.layer.ensure_pipeline(
            CreatePipelineRequest(
                id=self.settings.extraction_pipeline_id,
                target_namespace=self.settings.namespace,
                distance_metric=self.settings.distance_metric,
            )
        )

    async def process_refresh_control(self, catalog_run_id: str) -> bool:
        if catalog_run_id not in self._enqueued_refresh_labels:
            jobs_created = await self.enqueue_scheduled_refresh(catalog_run_id)
            self._enqueued_refresh_labels.add(catalog_run_id)
            logger.info(
                "scheduled refresh enqueued extraction jobs",
                extra={
                    "catalog_run_id": catalog_run_id,
                    "jobs_created": jobs_created,
                },
            )

        deadline = (
            asyncio.get_running_loop().time()
            + max(0.0, self.settings.scheduled_checkpoint_wait_seconds)
        )
        while True:
            if await self.ingest_stable_for_refresh():
                checkpoint = await self.layer.create_checkpoint(
                    self.settings.namespace, {"label": catalog_run_id}
                )
                logger.info(
                    "activated scheduled catalog checkpoint",
                    extra={
                        "catalog_run_id": catalog_run_id,
                        "watermark_ms": getattr(checkpoint, "watermark_ms", None),
                        "row_count": getattr(checkpoint, "row_count", None),
                    },
                )
                return True

            if asyncio.get_running_loop().time() >= deadline:
                logger.warning(
                    "scheduled refresh did not stabilize before checkpoint wait deadline",
                    extra={"catalog_run_id": catalog_run_id},
                )
                return False

            await asyncio.sleep(
                max(1.0, self.settings.scheduled_checkpoint_poll_seconds)
            )

    async def enqueue_scheduled_refresh(self, catalog_run_id: str) -> int:
        source_offset = await self.checkpoint_row_cursor()
        jobs = build_scheduled_index_jobs(
            pipeline_id=self.settings.default_pipeline_id,
            namespace=self.settings.namespace,
            category=self.settings.default_category,
            catalog_run_id=catalog_run_id,
            row_offset=source_offset,
            count=self.settings.scheduled_refresh_count,
            job_size=self.settings.extraction_job_size,
        )
        if not jobs:
            return 0

        response = await self.layer.set_documents_stage(
            self.settings.extraction_pipeline_id,
            SetDocumentsStageRequest(
                document_ids=[job.id for job in jobs],
                stage="pending",
                create_missing=True,
            ),
        )
        return int(response.updated)

    async def checkpoint_row_cursor(self) -> int:
        total = 0
        before: str | None = None
        while True:
            page = await self.layer.list_checkpoints(
                self.settings.namespace, limit=100, before=before
            )
            checkpoints = list(page.checkpoints)
            total += sum(max(0, int(checkpoint.row_count)) for checkpoint in checkpoints)
            before = page.next_cursor
            if not before:
                return total

    async def ingest_stable_for_refresh(self) -> bool:
        extraction_status = await self.layer.get_pipeline_status(
            self.settings.extraction_pipeline_id
        )
        product_status = await self.layer.get_pipeline_status(
            self.settings.default_pipeline_id
        )
        return self._pipeline_stable(
            extraction_status, allowed_processing=1
        ) and self._pipeline_stable(product_status)

    @staticmethod
    def _pipeline_stable(status: Any, *, allowed_processing: int = 0) -> bool:
        return (
            int(getattr(status, "pending_count", 0)) == 0
            and int(getattr(status, "processing_count", 0)) <= allowed_processing
            and int(getattr(status, "failed_count", 0)) == 0
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
        if processed == 0 and not job.skip_existing:
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
                    staged = await stage_product(
                        self.layer,
                        job.pipeline_id,
                        job.namespace,
                        product,
                        skip_existing=job.skip_existing,
                    )
                    if staged:
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
