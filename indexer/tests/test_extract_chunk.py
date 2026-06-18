from __future__ import annotations

import unittest
from unittest.mock import patch

from hevlayer import Checkpoint, PipelineStatus

from extract_chunk import (
    ExtractionWorker,
    build_scheduled_index_jobs,
    refresh_document_id,
    scheduled_extraction_job,
)
from hev_shop_common.records import ProductRecord

from _fakes import FakeLayerClient, make_settings


class FakeDataset:
    def __init__(self, products: list[ProductRecord]) -> None:
        self.products = products
        self.calls: list[dict[str, int | str]] = []

    def iter_products(self, *, category: str, offset: int = 0, limit: int = 100):
        self.calls.append({"category": category, "offset": offset, "limit": limit})
        products = self.products[offset:]
        if limit >= 0:
            products = products[:limit]
        return iter(products)


class ExtractionWorkerScheduledTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_seed_creates_one_refresh_control_document(self) -> None:
        layer = FakeLayerClient()
        worker = ExtractionWorker(
            settings=make_settings(scheduled_pipeline=True),
            layer=layer,
            dataset=FakeDataset([]),
        )

        with patch("extract_chunk.default_catalog_run_id", return_value="catalog-2026-06-15"):
            await worker.seed_scheduled_refresh()
            await worker.seed_scheduled_refresh()

        self.assertEqual(len(layer.set_stage_calls), 1)
        self.assertEqual(
            layer.set_stage_calls[0]["doc_ids"],
            [refresh_document_id("catalog-2026-06-15")],
        )
        self.assertTrue(layer.set_stage_calls[0]["create_missing"])

    async def test_refresh_control_enqueues_from_checkpoint_cursor_and_activates(self) -> None:
        layer = FakeLayerClient()
        layer.checkpoints = [
            Checkpoint(
                namespace="amazon-products",
                label="catalog-2026-06-14",
                watermark_ms=1000,
                sha="old",
                row_count=5,
            )
        ]
        layer.pipeline_statuses = {
            "hev-shop-extraction-jobs": PipelineStatus(
                pipeline_id="hev-shop-extraction-jobs",
                counts={"extracting": 1},
                pending_count=0,
                processing_count=1,
                failed_count=0,
                indexed_rate_per_min=0.0,
                rate_window_seconds=60,
            ),
            "hev-shop-product-images": PipelineStatus(
                pipeline_id="hev-shop-product-images",
                counts={},
                pending_count=0,
                processing_count=0,
                failed_count=0,
                indexed_rate_per_min=0.0,
                rate_window_seconds=60,
            ),
        }
        settings = make_settings(
            scheduled_refresh_count=3,
            extraction_job_size=2,
            scheduled_checkpoint_wait_seconds=0.01,
        )
        worker = ExtractionWorker(settings=settings, layer=layer, dataset=FakeDataset([]))

        activated = await worker.process_refresh_control("catalog-2026-06-15")

        self.assertTrue(activated)
        jobs = build_scheduled_index_jobs(
            pipeline_id="hev-shop-product-images",
            namespace="amazon-products",
            category="Electronics",
            catalog_run_id="catalog-2026-06-15",
            row_offset=5,
            count=3,
            job_size=2,
        )
        self.assertEqual(layer.set_stage_calls[0]["doc_ids"], [job.id for job in jobs])
        self.assertEqual(
            layer.checkpoint_calls,
            [
                {
                    "namespace": "amazon-products",
                    "body": {"label": "catalog-2026-06-15"},
                }
            ],
        )

    async def test_scheduled_job_id_processes_without_chunks_and_skips_existing(self) -> None:
        products = [
            ProductRecord(asin="A1", category="Electronics", image_url="https://e.test/1.jpg"),
            ProductRecord(asin="A2", category="Electronics", image_url="https://e.test/2.jpg"),
        ]
        layer = FakeLayerClient()
        layer.existing_documents.add(("amazon-products", "A1"))
        job = scheduled_extraction_job(
            pipeline_id="hev-shop-product-images",
            namespace="amazon-products",
            category="Electronics",
            catalog_run_id="catalog-2026-06-15",
            row_offset=0,
            row_limit=2,
        )
        layer.next_claim = [job.id]
        worker = ExtractionWorker(
            settings=make_settings(extraction_concurrency=1),
            layer=layer,
            dataset=FakeDataset(products),
        )

        processed = await worker.process_once()

        self.assertEqual(processed, 1)
        self.assertEqual(layer.fetch_document_calls[0]["doc_id"], "A1")
        self.assertEqual(layer.fetch_document_calls[1]["doc_id"], "A2")
        self.assertEqual(
            [call["document_id"] for call in layer.stage_document_calls],
            ["A2"],
        )
        self.assertEqual(layer.complete_calls[0]["doc_ids"], [job.id])


if __name__ == "__main__":
    unittest.main()
