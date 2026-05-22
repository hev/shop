"""Phase-1 RED tests for the consolidated pipeline module.

Imports `STAGES`, `Stage`, `StageContext`, `StageOutcome`, `_run_once`
from `app.pipeline`. The driver tests use synthetic Stage entries to
exercise `_run_once` in isolation; the per-stage tests run the real
STAGES entries against fake LayerClient/embedders/classifier.

When all of these go green, this file replaces
`test_workers_characterization.py`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.classifier import ReviewTag
from app.pipeline import (
    STAGES,
    Stage,
    StageContext,
    StageOutcome,
    _run_once,
)

from _fakes import (
    FakeClassifier,
    FakeClipImageEmbedder,
    FakeLayerClient,
    FakeQwenTextEmbedder,
    make_settings,
)


def make_ctx(
    layer: FakeLayerClient | None = None,
    settings=None,
    **embedder_overrides,
) -> StageContext:
    ctx = StageContext(
        settings=settings or make_settings(),
        layer=layer or FakeLayerClient(),
    )
    for key, value in embedder_overrides.items():
        setattr(ctx, key, value)
    return ctx


# ---------------------------------------------------------------------------
# Manifest: the N-stage pipeline at a glance
# ---------------------------------------------------------------------------


class StageManifestTests(unittest.TestCase):
    def test_embed_products(self) -> None:
        stage = STAGES["embed-products"]
        self.assertEqual(stage.pipeline_attr, "default_pipeline_id")
        self.assertEqual(stage.from_stage, "embedding")
        self.assertEqual(stage.claim_size_attr, "embedding_claim_size")
        self.assertIsNone(stage.prefix)

    def test_embed_reviews(self) -> None:
        stage = STAGES["embed-reviews"]
        self.assertEqual(stage.pipeline_attr, "reviews_pipeline_id")
        self.assertEqual(stage.from_stage, "embedding")
        self.assertEqual(stage.claim_size_attr, "embedding_claim_size")
        self.assertEqual(stage.prefix, "review-embed:")
        self.assertIsNotNone(stage.setup)

    def test_classify_reviews(self) -> None:
        stage = STAGES["classify-reviews"]
        self.assertEqual(stage.pipeline_attr, "reviews_pipeline_id")
        self.assertEqual(stage.from_stage, "classifying")
        self.assertEqual(stage.claim_size_attr, "review_classification_batch_size")
        self.assertEqual(stage.prefix, "review-classify:")

    def test_aggregate_tags(self) -> None:
        stage = STAGES["aggregate-tags"]
        self.assertEqual(stage.pipeline_attr, "review_aggregate_pipeline_id")
        self.assertEqual(stage.from_stage, "aggregating")
        self.assertEqual(stage.claim_size_attr, "review_aggregate_batch_size")
        self.assertIsNone(stage.prefix)


# ---------------------------------------------------------------------------
# Driver: _run_once owns claim/heartbeat/release; everything else
# routes via the StageOutcome returned by `process`.
# ---------------------------------------------------------------------------


def synthetic_stage(process) -> Stage:
    return Stage(
        name="synthetic",
        pipeline_attr="default_pipeline_id",
        from_stage="embedding",
        claim_size_attr="embedding_claim_size",
        process=process,
    )


class DriverTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_claim_returns_zero_and_makes_no_other_calls(self) -> None:
        layer = FakeLayerClient()
        ctx = make_ctx(layer=layer)

        async def process(_ctx, _doc_ids):
            self.fail("process should not run on empty claim")

        result = await _run_once(synthetic_stage(process), ctx)

        self.assertEqual(result, 0)
        self.assertEqual(len(layer.claim_calls), 1)
        self.assertEqual(layer.complete_calls, [])
        self.assertEqual(layer.fail_calls, [])
        self.assertEqual(layer.release_calls, [])
        self.assertEqual(layer.heartbeat_calls, [])

    async def test_outcome_routes_complete_fail_release_to_layer_calls(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["a", "b", "c", "d"]
        ctx = make_ctx(layer=layer)

        async def process(_ctx, doc_ids):
            self.assertEqual(doc_ids, ["a", "b", "c", "d"])
            return StageOutcome(complete=["a"], fail=["b"], release=["c"])
            # 'd' intentionally left out; the driver should release it so a
            # stage bug cannot strand a claimed document forever.

        result = await _run_once(synthetic_stage(process), ctx)

        self.assertEqual(result, 1)
        self.assertEqual(layer.complete_calls[0]["doc_ids"], ["a"])
        self.assertEqual(layer.complete_calls[0]["from_stage"], "embedding")
        self.assertEqual(layer.fail_calls[0]["doc_ids"], ["b"])
        self.assertEqual(layer.fail_calls[0]["from_stage"], "embedding")
        self.assertEqual(layer.release_calls[0]["doc_ids"], ["c", "d"])
        self.assertEqual(layer.release_calls[0]["from_stage"], "embedding")

    async def test_process_raising_releases_all_claimed_and_propagates(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["x", "y"]
        ctx = make_ctx(layer=layer)

        async def process(_ctx, _doc_ids):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            await _run_once(synthetic_stage(process), ctx)

        self.assertEqual(sorted(layer.release_calls[0]["doc_ids"]), ["x", "y"])
        self.assertEqual(layer.release_calls[0]["from_stage"], "embedding")
        self.assertEqual(layer.complete_calls, [])
        self.assertEqual(layer.fail_calls, [])

    async def test_claim_args_come_from_stage_definition(self) -> None:
        layer = FakeLayerClient()
        ctx = make_ctx(layer=layer)
        stage = Stage(
            name="synthetic",
            pipeline_attr="reviews_pipeline_id",
            from_stage="classifying",
            claim_size_attr="review_classification_batch_size",
            prefix="review-classify:",
            process=lambda _c, _d: None,  # never invoked (empty claim)
        )

        await _run_once(stage, ctx)

        call = layer.claim_calls[0]
        self.assertEqual(call["pipeline_id"], "hev-shop-reviews")
        self.assertEqual(call["claim_stage"], "classifying")
        self.assertEqual(call["prefix"], "review-classify:")
        self.assertEqual(call["limit"], 4)


# ---------------------------------------------------------------------------
# Per-stage tests — same observable contract as phase-0, just funnelled
# through the driver + STAGES manifest instead of the worker classes.
# ---------------------------------------------------------------------------


class EmbedProductsStageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.layer = FakeLayerClient()
        self.embedder = FakeClipImageEmbedder()
        self.tmp = TemporaryDirectory()
        self.image_path = Path(self.tmp.name) / "A1.jpg"
        self.image_path.write_bytes(b"\xff\xd8\xff")
        self.ctx = make_ctx(
            layer=self.layer,
            _clip_image=self.embedder,
        )
        self.stage = STAGES["embed-products"]

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_empty_claim_returns_zero(self) -> None:
        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.claim_calls[0]["claim_stage"], "embedding")
        self.assertEqual(self.layer.claim_calls[0]["pipeline_id"], "hev-shop-product-images")
        self.assertIsNone(self.layer.claim_calls[0]["prefix"])
        self.assertEqual(self.layer.upsert_calls, [])

    async def test_setup_creates_pipeline_and_warms_clip_before_claim(self) -> None:
        layer = FakeLayerClient()
        ctx = make_ctx(layer=layer)

        with patch("hev_shop_common.embedders.CLIPImageEmbedder", return_value=self.embedder) as ctor:
            await self.stage.setup(ctx)

        self.assertEqual(
            layer.create_pipeline_calls,
            [("hev-shop-product-images", "amazon-products", "cosine_distance")],
        )
        ctor.assert_called_once_with(ctx.settings)
        self.assertIs(ctx._clip_image, self.embedder)
        self.assertEqual(layer.claim_calls, [])

    async def test_happy_path_upserts_product_attrs_and_completes(self) -> None:
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

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 1)
        self.assertEqual(len(self.layer.upsert_calls), 1)
        upsert = self.layer.upsert_calls[0]
        self.assertEqual(upsert["namespace"], "amazon-products")
        self.assertEqual(upsert["vectors"][0]["id"], "A1")
        attrs = upsert["vectors"][0]["attributes"]
        self.assertEqual(attrs["asin"], "A1")
        self.assertNotIn("tags", attrs)
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.complete_calls[0]["from_stage"], "embedding")

    async def test_happy_path_includes_image_blob_on_upsert(self) -> None:
        from base64 import b64decode

        self.layer.next_claim = ["A1"]
        self.layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "metadata": {
                        "asin": "A1",
                        "image_path": str(self.image_path),
                    },
                }
            ]
        }

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 1)
        blobs = self.layer.upsert_calls[0]["vectors"][0]["blobs"]
        self.assertIn("image", blobs)
        self.assertEqual(blobs["image"]["content_type"], "image/jpeg")
        self.assertEqual(b64decode(blobs["image"]["data"]), b"\xff\xd8\xff")

    async def test_oversize_blob_skipped_but_vector_still_written(self) -> None:
        # 8 bytes payload, cap at 4 — the blob must drop while the vector
        # write still wins.
        self.image_path.write_bytes(b"\xff" * 8)
        ctx = make_ctx(
            layer=self.layer,
            _clip_image=self.embedder,
            settings=make_settings(blob_max_bytes=4),
        )
        self.layer.next_claim = ["A1"]
        self.layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "metadata": {"asin": "A1", "image_path": str(self.image_path)},
                }
            ]
        }

        result = await _run_once(self.stage, ctx)

        self.assertEqual(result, 1)
        upsert_doc = self.layer.upsert_calls[0]["vectors"][0]
        self.assertEqual(upsert_doc["id"], "A1")
        self.assertEqual(upsert_doc.get("blobs", {}), {})
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], ["A1"])

    async def test_unknown_suffix_skips_blob_but_vector_still_written(self) -> None:
        weird = Path(self.tmp.name) / "A1.bin"
        weird.write_bytes(b"abc")
        self.layer.next_claim = ["A1"]
        self.layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "metadata": {"asin": "A1", "image_path": str(weird)},
                }
            ]
        }

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 1)
        upsert_doc = self.layer.upsert_calls[0]["vectors"][0]
        self.assertEqual(upsert_doc.get("blobs", {}), {})
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], ["A1"])

    async def test_missing_chunks_fails_document(self) -> None:
        self.layer.next_claim = ["A1"]
        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.fail_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.fail_calls[0]["from_stage"], "embedding")

    async def test_missing_image_fails_document(self) -> None:
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

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.fail_calls[0]["doc_ids"], ["A1"])

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

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.complete_calls, [])
        self.assertEqual(self.layer.upsert_calls, [])


class EmbedReviewsStageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.layer = FakeLayerClient()
        self.embedder = FakeQwenTextEmbedder()
        self.ctx = make_ctx(layer=self.layer, _qwen=self.embedder)
        self.stage = STAGES["embed-reviews"]

    async def test_claims_with_review_embed_prefix(self) -> None:
        await _run_once(self.stage, self.ctx)

        call = self.layer.claim_calls[0]
        self.assertEqual(call["pipeline_id"], "hev-shop-reviews")
        self.assertEqual(call["claim_stage"], "embedding")
        self.assertEqual(call["prefix"], "review-embed:")

    async def test_setup_creates_pipeline_and_warms_qwen_before_claim(self) -> None:
        layer = FakeLayerClient()
        ctx = make_ctx(layer=layer)

        with patch("hev_shop_common.embedders.QwenTextEmbedder", return_value=self.embedder) as ctor:
            await self.stage.setup(ctx)

        self.assertEqual(
            layer.create_pipeline_calls,
            [("hev-shop-reviews", "amazon-reviews", "cosine_distance")],
        )
        ctor.assert_called_once_with(ctx.settings)
        self.assertIs(ctx._qwen, self.embedder)
        self.assertEqual(layer.claim_calls, [])

    async def test_happy_path_upserts_to_sharded_namespace(self) -> None:
        from hev_shop_common.records import REVIEW_EMBED_PREFIX, review_namespace_for

        doc_id = f"{REVIEW_EMBED_PREFIX}r-1"
        self.layer.next_claim = [doc_id]
        self.layer.chunks_by_doc_id = {
            doc_id: [
                {
                    "id": "review-raw:r-1",
                    "text": "great camera",
                    "metadata": {
                        "asin": "A1",
                        "review_id": "r-1",
                        "category": "Electronics",
                        "rating": 5,
                    },
                }
            ]
        }

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 1)
        expected_ns = review_namespace_for(
            "A1", namespace_base="amazon-reviews", shard_count=4
        )
        upsert = self.layer.upsert_calls[0]
        self.assertEqual(upsert["namespace"], expected_ns)
        self.assertEqual(upsert["vectors"][0]["id"], "r-1:chunk:0000")
        self.assertEqual(upsert["vectors"][0]["attributes"]["asin"], "A1")
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], [doc_id])

    async def test_embed_hands_off_to_classify_when_requested(self) -> None:
        doc_id = "review-embed:r-1"
        self.layer.next_claim = [doc_id]
        self.layer.chunks_by_doc_id = {
            doc_id: [
                {
                    "id": "review-raw:r-1",
                    "text": "great camera",
                    "metadata": {
                        "asin": "A1",
                        "review_id": "r-1",
                        "enqueue_classify": True,
                    },
                }
            ]
        }

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 1)
        handoff = self.layer.stage_document_calls[0]
        self.assertEqual(handoff["pipeline_id"], "hev-shop-reviews")
        self.assertEqual(handoff["document_id"], "review-classify:r-1")
        self.assertNotIn("enqueue_classify", handoff["chunks"][0]["metadata"])

    async def test_missing_asin_or_text_fails_document(self) -> None:
        self.layer.next_claim = ["review-embed:bad"]
        self.layer.chunks_by_doc_id = {
            "review-embed:bad": [
                {"id": "review-raw:bad", "text": "", "metadata": {"asin": ""}}
            ]
        }

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.fail_calls[0]["doc_ids"], ["review-embed:bad"])

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

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], [doc_id])
        self.assertEqual(self.layer.complete_calls, [])


class ClassifyReviewsStageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.layer = FakeLayerClient()
        self.classifier = FakeClassifier()
        self.ctx = make_ctx(layer=self.layer, _classifier=self.classifier)
        self.stage = STAGES["classify-reviews"]

    async def test_claims_with_classify_prefix_and_stage(self) -> None:
        await _run_once(self.stage, self.ctx)

        call = self.layer.claim_calls[0]
        self.assertEqual(call["pipeline_id"], "hev-shop-reviews")
        self.assertEqual(call["claim_stage"], "classifying")
        self.assertEqual(call["prefix"], "review-classify:")
        self.assertEqual(call["limit"], 4)

    async def test_missing_api_key_releases_all_claimed_docs(self) -> None:
        # NOTE: this is a deliberate behavior shift from the old worker,
        # which short-circuited *before* claiming. The new shape claims
        # then releases when the api key is unset — observable end-state
        # is identical (no progress, no tags written).
        self.ctx.settings.openrouter_api_key = None
        self.layer.next_claim = ["review-classify:r-1"]

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], ["review-classify:r-1"])
        self.assertEqual(self.classifier.calls, [])
        self.assertEqual(self.layer.set_stage_calls, [])

    async def test_happy_path_patches_review_vector_and_hands_off_to_aggregate(self) -> None:
        from hev_shop_common.records import review_namespace_for

        doc_id = "review-classify:r-1"
        self.layer.next_claim = [doc_id]
        review_namespace = review_namespace_for(
            "A1", namespace_base="amazon-reviews", shard_count=4
        )
        self.layer.documents_by_namespace[(review_namespace, "r-1:chunk:0000")] = {
            "attributes": {"review_id": "r-1"}
        }
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

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 1)
        patch = self.layer.patch_calls[0]
        self.assertEqual(patch["namespace"], review_namespace)
        self.assertEqual(patch["patches"][0]["id"], "r-1:chunk:0000")
        self.assertEqual(patch["patches"][0]["attributes"]["tags"], ["Value Leader"])
        self.assertEqual(
            patch["patches"][0]["attributes"]["tag_confidences"],
            '{"Value Leader":0.9}',
        )
        # Cross-stage hand-off: aggregate pipeline gets A1 transitioned
        # to pending so the aggregate-tags stage can pick it up next.
        hand_off = self.layer.set_stage_calls[0]
        self.assertEqual(hand_off["pipeline_id"], "hev-shop-review-tags")
        self.assertEqual(hand_off["doc_ids"], ["A1"])
        self.assertEqual(hand_off["stage"], "pending")
        self.assertTrue(hand_off["create_missing"])
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], [doc_id])
        self.assertEqual(self.layer.complete_calls[0]["from_stage"], "classifying")

    async def test_missing_review_vector_releases_doc_and_skips_classifier(self) -> None:
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

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], [doc_id])
        self.assertEqual(self.layer.release_calls[0]["from_stage"], "classifying")
        self.assertEqual(self.classifier.calls, [])
        self.assertEqual(self.layer.set_stage_calls, [])

    async def test_classifier_raises_releases_all_docs(self) -> None:
        from hev_shop_common.records import review_namespace_for

        self.classifier.raise_on_call = True
        doc_id = "review-classify:r-1"
        self.layer.next_claim = [doc_id]
        review_namespace = review_namespace_for(
            "A1", namespace_base="amazon-reviews", shard_count=4
        )
        self.layer.documents_by_namespace[(review_namespace, "r-1:chunk:0000")] = {
            "attributes": {"review_id": "r-1"}
        }
        self.layer.chunks_by_doc_id = {
            doc_id: [
                {
                    "id": "review-raw:r-1",
                    "text": "Built to last",
                    "metadata": {"asin": "A1", "review_id": "r-1"},
                }
            ]
        }

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], [doc_id])
        self.assertEqual(self.layer.complete_calls, [])
        self.assertEqual(self.layer.set_stage_calls, [])


class AggregateTagsStageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from hev_shop_common.records import review_namespace_for

        self.layer = FakeLayerClient()
        ns_a1 = review_namespace_for(
            "A1", namespace_base="amazon-reviews", shard_count=4
        )
        ns_a2 = review_namespace_for(
            "A2", namespace_base="amazon-reviews", shard_count=4
        )
        self.layer.scan_results_by_namespace.setdefault(ns_a1, []).extend([
            {
                "attributes": {
                    "asin": "A1",
                    "review_id": f"a1-r-{idx}",
                    "tags": ["Value Leader"],
                    "tag_confidences": '{"Value Leader":0.9}',
                    "review_classified_at": "2026-05-18T00:00:00+00:00",
                }
            }
            for idx in range(3)
        ])
        self.layer.scan_results_by_namespace.setdefault(ns_a2, []).extend([
            {
                "attributes": {
                    "asin": "A2",
                    "review_id": f"a2-r-{idx}",
                    "tags": ["Overpriced"],
                    "tag_confidences": '{"Overpriced":0.8}',
                    "review_classified_at": "2026-05-18T00:00:00+00:00",
                }
            }
            for idx in range(3)
        ])
        self.ctx = make_ctx(layer=self.layer)
        self.stage = STAGES["aggregate-tags"]

    async def test_claims_with_aggregating_stage(self) -> None:
        await _run_once(self.stage, self.ctx)

        call = self.layer.claim_calls[0]
        self.assertEqual(call["pipeline_id"], "hev-shop-review-tags")
        self.assertEqual(call["claim_stage"], "aggregating")
        self.assertIsNone(call["prefix"])

    async def test_happy_path_patches_product_namespace_and_completes(self) -> None:
        self.layer.next_claim = ["A1", "A2"]

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 2)
        patch = self.layer.patch_calls[0]
        self.assertEqual(patch["namespace"], "amazon-products")
        self.assertEqual([p["id"] for p in patch["patches"]], ["A1", "A2"])
        self.assertEqual(patch["patches"][0]["attributes"]["tags"], ["Value Leader"])
        self.assertEqual(self.layer.complete_calls[0]["doc_ids"], ["A1", "A2"])
        self.assertEqual(self.layer.complete_calls[0]["from_stage"], "aggregating")

    async def test_patch_attributes_raises_releases_batch(self) -> None:
        self.layer.next_claim = ["A1"]

        async def boom(_namespace, _patches, *, with_perf=False):
            raise RuntimeError("turbopuffer down")

        self.layer.patch_documents = boom  # type: ignore[assignment]

        result = await _run_once(self.stage, self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(self.layer.release_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(self.layer.complete_calls, [])


if __name__ == "__main__":
    unittest.main()
