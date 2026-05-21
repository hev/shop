from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from contextlib import suppress
from uuid import uuid4

import httpx
from hevlayer import (
    AsyncHevlayer,
    Chunk,
    ClaimDocumentsRequest,
    CreatePipelineRequest,
    HeartbeatDocumentsRequest,
    PutChunksRequest,
    SetDocumentsStageRequest,
)

from hev_shop_common.config import Settings
from hev_shop_common.records import (
    ProductRecord,
    ReviewRecord,
    review_raw_chunk_id,
    review_work_document_id,
)

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


async def stage_review(
    layer: AsyncHevlayer,
    pipeline_id: str,
    review: ReviewRecord,
    *,
    work_item: str,
    enqueue_classify: bool = False,
) -> None:
    if work_item not in {"embed", "classify"}:
        raise ValueError("work_item must be 'embed' or 'classify'")
    metadata = review.attributes()
    if work_item == "embed" and enqueue_classify:
        metadata["enqueue_classify"] = True
    await layer.put_pipeline_document_chunks(
        pipeline_id,
        review_work_document_id(work_item, review.review_id),
        PutChunksRequest(
            chunks=[
                Chunk(
                    id=review_raw_chunk_id(review.review_id),
                    text=review.document_text(),
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
        self._http = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=settings.image_download_concurrency),
        )

    async def close(self) -> None:
        await self._http.aclose()

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
        except Exception as exc:
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
        await self.layer.ensure_pipeline(
            CreatePipelineRequest(
                id=self.settings.reviews_pipeline_id,
                target_namespace=self.settings.reviews_namespace_base,
                distance_metric=self.settings.distance_metric,
            )
        )
        self.settings.image_dir.mkdir(parents=True, exist_ok=True)

        if job.job_kind == "backfill":
            return await self.process_backfill_job(job)
        return await self.process_index_job(job)

    async def process_index_job(self, job: ExtractionJob) -> int:
        products = list(
            self.dataset.iter_products(
                category=job.category, offset=job.row_offset, limit=job.row_limit
            )
        )
        processed, staged_asins = await self.stage_products(job, products)
        review_count = await self.stage_reviews_for_asins(
            job,
            staged_asins,
            recent_limit=self.settings.review_recent_cap_per_product,
            helpful_limit=self.settings.review_helpful_cap_per_product,
            max_total_reviews=None,
            work_items=("embed", "classify"),
        )
        logger.info(
            "completed extraction job",
            extra={
                "job_id": job.id,
                "processed_count": processed,
                "reviews_staged": review_count,
            },
        )
        if processed == 0:
            raise RuntimeError("extraction job did not stage any products")
        return processed

    async def process_backfill_job(self, job: ExtractionJob) -> int:
        if job.target_asins:
            staged_asins = set(job.target_asins)
        else:
            # row_limit carries product_limit for dataset-driven backfill.
            # -1 means "all products in the category".
            limit = job.row_limit
            staged_asins = {
                product.asin
                for product in self.dataset.iter_products(
                    category=job.category, offset=0, limit=limit
                )
            }

        stages = job.review_stages or ("embed", "classify", "aggregate")
        review_work_items = tuple(s for s in stages if s in ("embed", "classify"))

        review_count = 0
        if review_work_items:
            per_product = (
                job.reviews_per_product
                if job.reviews_per_product is not None
                else self.settings.review_recent_cap_per_product
            )
            # Split per-product cap between recent and helpful heaps. The two
            # selections dedupe by review_id, so the effective per-product
            # count lands in [per_product, 2*per_product] before global cap.
            recent_limit = max(0, per_product // 2)
            helpful_limit = max(0, per_product - recent_limit)
            review_count = await self.stage_reviews_for_asins(
                job,
                staged_asins,
                recent_limit=recent_limit,
                helpful_limit=helpful_limit,
                max_total_reviews=job.max_total_reviews,
                work_items=review_work_items,
            )

        aggregate_count = 0
        if "aggregate" in stages and staged_asins:
            await self.layer.ensure_pipeline(
                CreatePipelineRequest(
                    id=self.settings.review_aggregate_pipeline_id,
                    target_namespace=self.settings.namespace,
                    distance_metric=self.settings.distance_metric,
                )
            )
            response = await self.layer.set_documents_stage(
                self.settings.review_aggregate_pipeline_id,
                SetDocumentsStageRequest(
                    document_ids=sorted(staged_asins),
                    stage="pending",
                    create_missing=True,
                ),
            )
            aggregate_count = response.updated

        logger.info(
            "completed backfill job",
            extra={
                "job_id": job.id,
                "asin_count": len(staged_asins),
                "reviews_staged": review_count,
                "aggregate_enqueued": aggregate_count,
                "stages": list(stages),
            },
        )
        # processed_count is set to the asin count so /status numbers remain
        # comparable across job kinds.
        return len(staged_asins)

    async def stage_products(
        self, job: ExtractionJob, products: list[ProductRecord]
    ) -> tuple[int, set[str]]:
        if not products:
            return 0, set()

        queue: asyncio.Queue[ProductRecord] = asyncio.Queue()
        for product in products:
            queue.put_nowait(product)

        async def worker() -> tuple[int, set[str]]:
            processed = 0
            staged_asins: set[str] = set()
            while True:
                try:
                    product = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    image_path = await self.download_image(product.asin, product.image_url)
                    await stage_product(
                        self.layer, job.pipeline_id, product.with_image_path(image_path)
                    )
                    processed += 1
                    staged_asins.add(product.asin)
                except Exception:
                    logger.exception(
                        "failed to stage product",
                        extra={"asin": product.asin, "pipeline_id": job.pipeline_id},
                    )
                finally:
                    queue.task_done()
            return processed, staged_asins

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
        processed = sum(result[0] for result in results)
        staged_asins = set().union(*(result[1] for result in results))
        return processed, staged_asins

    async def stage_reviews_for_asins(
        self,
        job: ExtractionJob,
        staged_asins: set[str],
        *,
        recent_limit: int,
        helpful_limit: int,
        max_total_reviews: int | None,
        work_items: tuple[str, ...],
    ) -> int:
        if not staged_asins or not work_items:
            return 0
        if recent_limit <= 0 and helpful_limit <= 0:
            return 0

        concurrency = max(1, self.settings.review_stage_concurrency)
        queue: asyncio.Queue[ReviewRecord | None] = asyncio.Queue(
            maxsize=concurrency * 2
        )

        async def producer() -> None:
            try:
                emitted = 0
                for review in self.dataset.iter_reviews_for_asins(
                    category=job.category,
                    asins=staged_asins,
                    recent_limit=recent_limit,
                    helpful_limit=helpful_limit,
                ):
                    if max_total_reviews is not None and emitted >= max_total_reviews:
                        break
                    await queue.put(review)
                    emitted += 1
            finally:
                for _ in range(concurrency):
                    await queue.put(None)

        async def consumer() -> int:
            staged = 0
            while True:
                review = await queue.get()
                try:
                    if review is None:
                        return staged
                    try:
                        stage_calls = []
                        if "embed" in work_items:
                            stage_calls.append(
                                stage_review(
                                    self.layer,
                                    self.settings.reviews_pipeline_id,
                                    review,
                                    work_item="embed",
                                    enqueue_classify="classify" in work_items,
                                )
                            )
                        elif "classify" in work_items:
                            stage_calls.append(
                                stage_review(
                                    self.layer,
                                    self.settings.reviews_pipeline_id,
                                    review,
                                    work_item="classify",
                                )
                            )
                        await asyncio.gather(*stage_calls)
                        staged += 1
                    except Exception:
                        logger.exception(
                            "failed to stage review",
                            extra={
                                "asin": review.asin,
                                "review_id": review.review_id,
                                "pipeline_id": self.settings.reviews_pipeline_id,
                            },
                        )
                finally:
                    queue.task_done()

        logger.info(
            "staging reviews for %s asins with concurrency %s",
            len(staged_asins),
            concurrency,
            extra={
                "job_id": job.id,
                "category": job.category,
                "work_items": list(work_items),
                "max_total_reviews": max_total_reviews,
            },
        )
        producer_task = asyncio.create_task(producer())
        consumer_tasks = [asyncio.create_task(consumer()) for _ in range(concurrency)]
        results = await asyncio.gather(*consumer_tasks)
        await producer_task
        return sum(results)

    async def download_image(self, asin: str, image_url: str) -> Path:
        suffix = Path(image_url.split("?", 1)[0]).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        target = self.settings.image_dir / f"{asin}{suffix}"
        if target.exists() and target.stat().st_size > 0:
            return target

        tmp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        response = await self._http.get(image_url)
        response.raise_for_status()
        try:
            await asyncio.to_thread(tmp.write_bytes, response.content)
            tmp.replace(target)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()
        return target
