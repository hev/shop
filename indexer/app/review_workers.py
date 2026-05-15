from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from .classifier import OpenRouterReviewClassifier, ReviewClassificationInput
from .config import Settings
from .database import Database
from .embedding import batches, run_worker_loop
from .layer_client import LayerClient
from .reviews import REVIEW_CLASSIFY_PREFIX

logger = logging.getLogger(__name__)


class ReviewClassifierWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        layer: LayerClient,
        classifier: OpenRouterReviewClassifier,
    ) -> None:
        self.settings = settings
        self.database = database
        self.layer = layer
        self.classifier = classifier
        self._pipelines_ready = False
        self._warned_missing_key = False

    async def close(self) -> None:
        await self.classifier.close()

    async def ensure_pipelines(self) -> None:
        if self._pipelines_ready:
            return
        await self.layer.create_pipeline(
            self.settings.reviews_pipeline_id,
            self.settings.reviews_namespace_base,
            self.settings.distance_metric,
        )
        await self.layer.create_pipeline(
            self.settings.review_aggregate_pipeline_id,
            self.settings.namespace,
            self.settings.distance_metric,
        )
        self._pipelines_ready = True

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        await self.ensure_pipelines()
        await run_worker_loop(
            self.process_once,
            poll_seconds=self.settings.worker_poll_seconds,
            stop_event=stop_event,
        )

    async def claim_documents(self) -> list[str]:
        return await self.layer.claim_pipeline_documents(
            self.settings.reviews_pipeline_id,
            limit=self.settings.review_classification_batch_size,
            worker_id=self.settings.resolved_worker_id,
            lease_seconds=self.settings.claim_lease_seconds,
            claim_stage="classifying",
            document_id_prefix=REVIEW_CLASSIFY_PREFIX,
        )

    async def release_documents(self, document_ids: list[str]) -> None:
        await self.layer.release_pipeline_documents(
            self.settings.reviews_pipeline_id,
            document_ids,
            from_stage="classifying",
            worker_id=self.settings.resolved_worker_id,
        )

    async def release_document(self, document_id: str) -> None:
        await self.release_documents([document_id])

    async def fail_documents(self, document_ids: list[str]) -> None:
        await self.layer.fail_pipeline_documents(
            self.settings.reviews_pipeline_id,
            document_ids,
            from_stage="classifying",
            worker_id=self.settings.resolved_worker_id,
        )

    async def complete_documents(self, document_ids: list[str]) -> None:
        await self.layer.complete_pipeline_documents(
            self.settings.reviews_pipeline_id,
            document_ids,
            from_stage="classifying",
            worker_id=self.settings.resolved_worker_id,
        )

    async def enqueue_review_aggregate_jobs(self, asins: list[str]) -> None:
        await self.layer.set_pipeline_documents_stage(
            self.settings.review_aggregate_pipeline_id,
            sorted(set(asins)),
            stage="pending",
            create_missing=True,
        )

    async def heartbeat_documents(self, active_doc_ids: set[str]) -> None:
        while True:
            await asyncio.sleep(self.settings.claim_heartbeat_seconds)
            await self.layer.heartbeat_pipeline_documents(
                self.settings.reviews_pipeline_id,
                sorted(active_doc_ids),
                stage="classifying",
                worker_id=self.settings.resolved_worker_id,
            )

    async def process_once(self) -> int:
        await self.ensure_pipelines()
        if not self.settings.openrouter_api_key:
            if not self._warned_missing_key:
                logger.warning("OPENROUTER_API_KEY is not set; review classifier is idle")
                self._warned_missing_key = True
            return 0
        doc_ids = await self.claim_documents()
        if not doc_ids:
            return 0
        active_doc_ids = set(doc_ids)
        heartbeat = asyncio.create_task(self.heartbeat_documents(active_doc_ids))

        try:
            if not await self.database.try_reserve_review_classification(
                usage_date=datetime.now(timezone.utc).date(),
                review_count=len(doc_ids),
                daily_review_limit=self.settings.review_classification_daily_review_limit,
            ):
                logger.warning("daily review classification cap reached")
                await self.release_documents(doc_ids)
                active_doc_ids.clear()
                return 0

            reviews: list[ReviewClassificationInput] = []
            doc_id_by_review: dict[str, str] = {}
            failed_doc_ids: list[str] = []
            for doc_id in doc_ids:
                try:
                    chunks = await self.layer.get_chunks(
                        self.settings.reviews_pipeline_id, doc_id
                    )
                    if not chunks:
                        failed_doc_ids.append(doc_id)
                        continue
                    chunk = chunks[0]
                    metadata = chunk.get("metadata") or {}
                    text = str(chunk.get("text") or "").strip()
                    asin = str(metadata.get("asin") or "")
                    review_id = str(metadata.get("review_id") or "")
                    if not asin or not review_id or not text:
                        failed_doc_ids.append(doc_id)
                        continue
                    doc_id_by_review[review_id] = doc_id
                    reviews.append(
                        ReviewClassificationInput(
                            asin=asin,
                            review_id=review_id,
                            rating=metadata.get("rating"),
                            title=metadata.get("title"),
                            text=text,
                        )
                    )
                except Exception:
                    logger.exception(
                        "failed to prepare review classification",
                        extra={"doc_id": doc_id},
                    )
                    await self.release_document(doc_id)
                    active_doc_ids.discard(doc_id)

            if failed_doc_ids:
                await self.fail_documents(failed_doc_ids)
                active_doc_ids.difference_update(failed_doc_ids)
            if not reviews:
                if active_doc_ids:
                    await self.release_documents(sorted(active_doc_ids))
                    active_doc_ids.clear()
                return 0

            try:
                classified = await self.classifier.classify(reviews)
            except Exception:
                logger.exception("review classifier request failed")
                await self.release_documents(sorted(active_doc_ids))
                active_doc_ids.clear()
                return 0

            completed: list[str] = []
            aggregate_asins: list[str] = []
            for review in reviews:
                tags = classified.get(review.review_id, [])
                await self.database.replace_review_classification(
                    asin=review.asin,
                    review_id=review.review_id,
                    tags=[(tag.tag, tag.confidence) for tag in tags],
                )
                aggregate_asins.append(review.asin)
                completed.append(doc_id_by_review[review.review_id])
            await self.enqueue_review_aggregate_jobs(aggregate_asins)
            await self.complete_documents(completed)
            active_doc_ids.difference_update(completed)
            logger.info("classified %s reviews", len(reviews))
            return len(reviews)
        except asyncio.CancelledError:
            if active_doc_ids:
                await self.release_documents(sorted(active_doc_ids))
                active_doc_ids.clear()
            raise
        except Exception:
            if active_doc_ids:
                await self.release_documents(sorted(active_doc_ids))
                active_doc_ids.clear()
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat


class ReviewAggregateWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        layer: LayerClient,
    ) -> None:
        self.settings = settings
        self.database = database
        self.layer = layer
        self._pipeline_ready = False

    async def ensure_pipeline(self) -> None:
        if self._pipeline_ready:
            return
        await self.layer.create_pipeline(
            self.settings.review_aggregate_pipeline_id,
            self.settings.namespace,
            self.settings.distance_metric,
        )
        self._pipeline_ready = True

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        await self.ensure_pipeline()
        await run_worker_loop(
            self.process_once,
            poll_seconds=self.settings.worker_poll_seconds,
            stop_event=stop_event,
        )

    async def claim_documents(self) -> list[str]:
        return await self.layer.claim_pipeline_documents(
            self.settings.review_aggregate_pipeline_id,
            limit=self.settings.vector_upsert_batch_size,
            worker_id=self.settings.resolved_worker_id,
            lease_seconds=self.settings.claim_lease_seconds,
            claim_stage="aggregating",
        )

    async def release_documents(self, document_ids: list[str]) -> None:
        await self.layer.release_pipeline_documents(
            self.settings.review_aggregate_pipeline_id,
            document_ids,
            from_stage="aggregating",
            worker_id=self.settings.resolved_worker_id,
        )

    async def complete_documents(self, document_ids: list[str]) -> None:
        await self.layer.complete_pipeline_documents(
            self.settings.review_aggregate_pipeline_id,
            document_ids,
            from_stage="aggregating",
            worker_id=self.settings.resolved_worker_id,
        )

    async def heartbeat_documents(self, active_doc_ids: set[str]) -> None:
        while True:
            await asyncio.sleep(self.settings.claim_heartbeat_seconds)
            await self.layer.heartbeat_pipeline_documents(
                self.settings.review_aggregate_pipeline_id,
                sorted(active_doc_ids),
                stage="aggregating",
                worker_id=self.settings.resolved_worker_id,
            )

    async def process_once(self) -> int:
        await self.ensure_pipeline()
        asins = await self.claim_documents()
        if not asins:
            return 0
        active_asins = set(asins)
        heartbeat = asyncio.create_task(self.heartbeat_documents(active_asins))

        try:
            processed = 0
            for asin_batch in batches(asins, self.settings.vector_upsert_batch_size):
                patches: list[dict[str, Any]] = []
                for asin in asin_batch:
                    attrs = await self.database.aggregate_review_tag_attrs(
                        asin,
                        min_count=self.settings.review_tag_min_count,
                        min_fraction=self.settings.review_tag_min_fraction,
                        sample_count=self.settings.review_tag_sample_count,
                    )
                    patches.append({"id": asin, "attributes": attrs})
                try:
                    await self.layer.patch_attributes(self.settings.namespace, patches)
                    await self.complete_documents(asin_batch)
                    active_asins.difference_update(asin_batch)
                    processed += len(asin_batch)
                except Exception:
                    logger.exception("failed to aggregate review tags")
                    await self.release_documents(asin_batch)
                    active_asins.difference_update(asin_batch)
            return processed
        except asyncio.CancelledError:
            if active_asins:
                await self.release_documents(sorted(active_asins))
                active_asins.clear()
            raise
        except Exception:
            if active_asins:
                await self.release_documents(sorted(active_asins))
                active_asins.clear()
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
