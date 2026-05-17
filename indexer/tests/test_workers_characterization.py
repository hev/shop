"""Characterization tests for the four worker classes.

These pin the observable contract — the exact LayerClient and Database
calls each worker makes — so the upcoming pipeline.py refactor has a
safety net. After phase 1 lands matching tests against the new
`STAGES` shape, this file can be deleted.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.classifier import ReviewTag
from app.embedding import EmbeddingWorker, ReviewEmbeddingWorker
from app.review_workers import ReviewAggregateWorker, ReviewClassifierWorker

from _fakes import (
    FakeClassifier,
    FakeClipImageEmbedder,
    FakeDatabase,
    FakeLayerClient,
    FakeQwenTextEmbedder,
    make_settings,
)


# ---------------------------------------------------------------------------
# EmbeddingWorker (CLIP product images)
# ---------------------------------------------------------------------------


class EmbeddingWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.layer = FakeLayerClient()
        self.database = FakeDatabase(
            tag_attrs_by_asin={
                "A1": {"tags": ["Value Leader"], "classified_review_count": 7}
            }
        )
        self.settings = make_settings()
        self.embedder = FakeClipImageEmbedder()
        self.tmp = TemporaryDirectory()
        self.image_path = Path(self.tmp.name) / "A1.jpg"
        self.image_path.write_bytes(b"\xff\xd8\xff")
        self.worker = EmbeddingWorker(
            settings=self.settings,
            database=self.database,
            layer=self.layer,
            embedder=self.embedder,
            pipeline_id="amazon-products-images",
            namespace_resolver=lambda _meta, _doc_id: "amazon-products",
            include_review_tag_attrs=True,
        )

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_empty_claim_returns_zero_and_does_not_upsert(self) -> None:
        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        self.assertEqual(len(self.layer.claim_calls), 1)
        self.assertEqual(self.layer.claim_calls[0]["claim_stage"], "embedding")
        self.assertEqual(self.layer.claim_calls[0]["pipeline_id"], "amazon-products-images")
        self.assertIsNone(self.layer.claim_calls[0]["prefix"])
        self.assertEqual(self.layer.upsert_calls, [])
        self.assertEqual(self.layer.complete_calls, [])

    async def test_happy_path_upserts_with_merged_tag_attrs_and_completes(self) -> None:
        self.layer.next_claim = ["A1"]
        self.layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "text": "title\ndesc",
                    "metadata": {
                        "asin": "A1",
                        "title": "Camera",
                        "category": "Electronics",
                        "image_url": "https://example.test/a.jpg",
                        "image_path": str(self.image_path),
                    },
                }
            ]
        }

        result = await self.worker.process_once()

        self.assertEqual(result, 1)
        self.assertEqual(len(self.layer.upsert_calls), 1)
        upsert = self.layer.upsert_calls[0]
        self.assertEqual(upsert["namespace"], "amazon-products")
        self.assertEqual(upsert["vectors"][0]["id"], "A1")
        attrs = upsert["vectors"][0]["attributes"]
        self.assertEqual(attrs["asin"], "A1")
        # review-tag rollup merged in because include_review_tag_attrs=True
        self.assertEqual(attrs["tags"], ["Value Leader"])
        self.assertEqual(attrs["classified_review_count"], 7)
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.complete_calls[0]["from_stage"], "embedding")
        self.assertEqual(self.layer.fail_calls, [])
        self.assertEqual(self.layer.release_calls, [])

    async def test_missing_chunks_fails_document(self) -> None:
        self.layer.next_claim = ["A1"]
        # no chunks_by_doc_id entry → get_chunks returns []

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.fail_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.fail_calls[0]["from_stage"], "embedding")
        self.assertEqual(self.layer.upsert_calls, [])

    async def test_missing_image_file_fails_document(self) -> None:
        self.layer.next_claim = ["A1"]
        self.layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "metadata": {
                        "asin": "A1",
                        "image_path": "/tmp/does-not-exist-xyz.jpg",
                    },
                }
            ]
        }

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.fail_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.upsert_calls, [])

    async def test_embedder_raises_releases_documents(self) -> None:
        self.embedder.raise_on_call = True
        self.layer.next_claim = ["A1"]
        self.layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "metadata": {"asin": "A1", "image_path": str(self.image_path)},
                }
            ]
        }

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        # release used for transient failure (CLIP raised); never complete
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.release_calls[0]["from_stage"], "embedding")
        self.assertEqual(self.layer.complete_calls, [])
        self.assertEqual(self.layer.upsert_calls, [])


# ---------------------------------------------------------------------------
# ReviewEmbeddingWorker (Qwen text)
# ---------------------------------------------------------------------------


class ReviewEmbeddingWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.layer = FakeLayerClient()
        self.database = FakeDatabase()
        self.settings = make_settings()
        self.embedder = FakeQwenTextEmbedder()
        self.worker = ReviewEmbeddingWorker(
            settings=self.settings,
            database=self.database,
            layer=self.layer,
            embedder=self.embedder,
        )

    async def test_claims_with_review_embed_prefix(self) -> None:
        await self.worker.process_once()

        call = self.layer.claim_calls[0]
        self.assertEqual(call["pipeline_id"], "hev-shop-reviews")
        self.assertEqual(call["claim_stage"], "embedding")
        self.assertEqual(call["prefix"], "review-embed:")

    async def test_happy_path_upserts_to_sharded_namespace_and_completes(self) -> None:
        from app.reviews import REVIEW_EMBED_PREFIX, review_namespace_for

        doc_id = f"{REVIEW_EMBED_PREFIX}r-1"
        self.layer.next_claim = [doc_id]
        self.layer.chunks_by_doc_id = {
            doc_id: [
                {
                    "id": "review-raw:r-1",
                    "text": "great camera, worth the money",
                    "metadata": {
                        "asin": "A1",
                        "review_id": "r-1",
                        "category": "Electronics",
                        "rating": 5,
                    },
                }
            ]
        }

        result = await self.worker.process_once()

        self.assertEqual(result, 1)
        expected_ns = review_namespace_for(
            "A1", namespace_base="amazon-reviews", shard_count=4
        )
        self.assertEqual(len(self.layer.upsert_calls), 1)
        upsert = self.layer.upsert_calls[0]
        self.assertEqual(upsert["namespace"], expected_ns)
        self.assertEqual(upsert["vectors"][0]["id"], "r-1:chunk:0000")
        self.assertEqual(upsert["vectors"][0]["attributes"]["asin"], "A1")
        self.assertEqual(upsert["vectors"][0]["attributes"]["chunk_idx"], 0)
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], [doc_id])

    async def test_missing_asin_or_text_fails_document(self) -> None:
        self.layer.next_claim = ["review-embed:bad"]
        self.layer.chunks_by_doc_id = {
            "review-embed:bad": [
                {"id": "review-raw:bad", "text": "", "metadata": {"asin": ""}}
            ]
        }

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.fail_calls[0]["doc_ids"], ["review-embed:bad"])
        self.assertEqual(self.layer.upsert_calls, [])

    async def test_embedder_raises_releases_documents(self) -> None:
        self.embedder.raise_on_encode = True
        doc_id = "review-embed:r-1"
        self.layer.next_claim = [doc_id]
        self.layer.chunks_by_doc_id = {
            doc_id: [
                {
                    "id": "review-raw:r-1",
                    "text": "great camera",
                    "metadata": {"asin": "A1", "review_id": "r-1"},
                }
            ]
        }

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], [doc_id])
        self.assertEqual(self.layer.complete_calls, [])
        self.assertEqual(self.layer.upsert_calls, [])


# ---------------------------------------------------------------------------
# ReviewClassifierWorker (cross-stage hand-off to aggregate pipeline)
# ---------------------------------------------------------------------------


class ReviewClassifierWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.layer = FakeLayerClient()
        self.database = FakeDatabase()
        self.settings = make_settings()
        self.classifier = FakeClassifier()
        self.worker = ReviewClassifierWorker(
            settings=self.settings,
            database=self.database,
            layer=self.layer,
            classifier=self.classifier,
        )

    async def test_missing_api_key_skips_claim_and_returns_zero(self) -> None:
        self.settings.openrouter_api_key = None

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        # ensure_pipelines still runs; claim does not
        self.assertEqual(self.layer.claim_calls, [])
        self.assertEqual(self.classifier.calls, [])

    async def test_claims_with_classify_prefix_and_stage(self) -> None:
        await self.worker.process_once()

        call = self.layer.claim_calls[0]
        self.assertEqual(call["pipeline_id"], "hev-shop-reviews")
        self.assertEqual(call["claim_stage"], "classifying")
        self.assertEqual(call["prefix"], "review-classify:")
        self.assertEqual(call["limit"], 4)

    async def test_happy_path_writes_tags_enqueues_aggregate_and_completes(self) -> None:
        doc_id = "review-classify:r-1"
        self.layer.next_claim = [doc_id]
        self.layer.chunks_by_doc_id = {
            doc_id: [
                {
                    "id": "review-raw:r-1",
                    "text": "Built to last",
                    "metadata": {
                        "asin": "A1",
                        "review_id": "r-1",
                        "rating": 5,
                        "title": "Great",
                    },
                }
            ]
        }
        self.classifier.response = {
            "r-1": [ReviewTag(review_id="r-1", tag="Value Leader", confidence=0.9)]
        }

        result = await self.worker.process_once()

        self.assertEqual(result, 1)
        # tags persisted to postgres
        self.assertEqual(
            self.database.replace_calls,
            [{"asin": "A1", "review_id": "r-1", "tags": [("Value Leader", 0.9)]}],
        )
        # cross-stage hand-off: aggregate pipeline gets A1 transitioned to pending
        self.assertEqual(len(self.layer.set_stage_calls), 1)
        hand_off = self.layer.set_stage_calls[0]
        self.assertEqual(hand_off["pipeline_id"], "amazon-products-review-tags")
        self.assertEqual(hand_off["doc_ids"], ["A1"])
        self.assertEqual(hand_off["stage"], "pending")
        self.assertTrue(hand_off["create_missing"])
        # source doc completed out of classifying
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], [doc_id])
        self.assertEqual(self.layer.complete_calls[0]["from_stage"], "classifying")

    async def test_daily_cap_releases_all_docs_and_skips_classifier(self) -> None:
        self.database.allow_reservation = False
        doc_id = "review-classify:r-1"
        self.layer.next_claim = [doc_id]

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], [doc_id])
        self.assertEqual(self.layer.release_calls[0]["from_stage"], "classifying")
        self.assertEqual(self.classifier.calls, [])
        self.assertEqual(self.layer.complete_calls, [])
        self.assertEqual(self.layer.set_stage_calls, [])

    async def test_classifier_raises_releases_all_docs(self) -> None:
        self.classifier.raise_on_call = True
        doc_id = "review-classify:r-1"
        self.layer.next_claim = [doc_id]
        self.layer.chunks_by_doc_id = {
            doc_id: [
                {
                    "id": "review-raw:r-1",
                    "text": "Built to last",
                    "metadata": {"asin": "A1", "review_id": "r-1"},
                }
            ]
        }

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], [doc_id])
        self.assertEqual(self.layer.complete_calls, [])
        self.assertEqual(self.layer.set_stage_calls, [])
        self.assertEqual(self.database.replace_calls, [])

    async def test_missing_chunk_fields_fail_that_doc(self) -> None:
        bad_doc = "review-classify:bad"
        good_doc = "review-classify:good"
        self.layer.next_claim = [bad_doc, good_doc]
        self.layer.chunks_by_doc_id = {
            bad_doc: [
                {"id": "review-raw:bad", "text": "", "metadata": {"asin": "A1"}}
            ],
            good_doc: [
                {
                    "id": "review-raw:good",
                    "text": "loved it",
                    "metadata": {"asin": "A1", "review_id": "good"},
                }
            ],
        }
        self.classifier.response = {"good": []}

        result = await self.worker.process_once()

        self.assertEqual(result, 1)
        self.assertEqual(self.layer.fail_calls[0]["doc_ids"], [bad_doc])
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], [good_doc])


# ---------------------------------------------------------------------------
# ReviewAggregateWorker (PATCH product rows with tag rollups)
# ---------------------------------------------------------------------------


class ReviewAggregateWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.layer = FakeLayerClient()
        self.database = FakeDatabase(
            tag_attrs_by_asin={
                "A1": {"tags": ["Value Leader"], "classified_review_count": 9},
                "A2": {"tags": ["Overpriced"], "classified_review_count": 4},
            }
        )
        self.settings = make_settings()
        self.worker = ReviewAggregateWorker(
            settings=self.settings,
            database=self.database,
            layer=self.layer,
        )

    async def test_claims_with_aggregating_stage(self) -> None:
        await self.worker.process_once()

        call = self.layer.claim_calls[0]
        self.assertEqual(call["pipeline_id"], "amazon-products-review-tags")
        self.assertEqual(call["claim_stage"], "aggregating")
        self.assertIsNone(call["prefix"])

    async def test_happy_path_patches_product_namespace_and_completes(self) -> None:
        self.layer.next_claim = ["A1", "A2"]

        result = await self.worker.process_once()

        self.assertEqual(result, 2)
        self.assertEqual(len(self.layer.patch_calls), 1)
        patch = self.layer.patch_calls[0]
        self.assertEqual(patch["namespace"], "amazon-products")
        self.assertEqual([p["id"] for p in patch["patches"]], ["A1", "A2"])
        self.assertEqual(
            patch["patches"][0]["attributes"]["tags"], ["Value Leader"]
        )
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], ["A1", "A2"])
        self.assertEqual(self.layer.complete_calls[0]["from_stage"], "aggregating")

    async def test_patch_attributes_raises_releases_batch(self) -> None:
        self.layer.next_claim = ["A1"]

        async def boom(_namespace, _patches):
            raise RuntimeError("turbopuffer down")

        self.layer.patch_attributes = boom  # type: ignore[assignment]

        result = await self.worker.process_once()

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.release_calls[0]["from_stage"], "aggregating")
        self.assertEqual(self.layer.complete_calls, [])


if __name__ == "__main__":
    unittest.main()
