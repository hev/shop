"""Shared test doubles for the indexer worker / pipeline contracts.

Lives outside the `test_*.py` collection pattern so pytest doesn't try
to run it. Both `test_workers_characterization.py` (phase-0) and
`test_pipeline.py` (phase-1) import from here.

Empty-list short-circuits in FakeLayerClient mirror the real
LayerClient: those calls never become HTTP requests in production, so
they shouldn't show up as recorded calls in tests either.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.classifier import ReviewTag


class FakeLayerClient:
    """Records every call; returns scripted claims/chunks."""

    def __init__(self) -> None:
        self.next_claim: list[str] = []
        self.chunks_by_doc_id: dict[str, list[dict[str, Any]]] = {}

        self.create_pipeline_calls: list[tuple[str, str, str]] = []
        self.claim_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self.fail_calls: list[dict[str, Any]] = []
        self.release_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.patch_calls: list[dict[str, Any]] = []
        self.heartbeat_calls: list[dict[str, Any]] = []
        self.set_stage_calls: list[dict[str, Any]] = []

    async def create_pipeline(self, pipeline_id, namespace, distance_metric):
        self.create_pipeline_calls.append((pipeline_id, namespace, distance_metric))

    async def claim_pipeline_documents(
        self,
        pipeline_id,
        *,
        limit,
        worker_id,
        lease_seconds,
        claim_stage,
        document_id_prefix=None,
    ):
        self.claim_calls.append(
            {
                "pipeline_id": pipeline_id,
                "limit": limit,
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
                "claim_stage": claim_stage,
                "prefix": document_id_prefix,
            }
        )
        head, self.next_claim = self.next_claim[:limit], self.next_claim[limit:]
        return list(head)

    async def heartbeat_pipeline_documents(
        self, pipeline_id, document_ids, *, stage, worker_id
    ):
        if not document_ids:
            return 0
        self.heartbeat_calls.append(
            {"pipeline_id": pipeline_id, "doc_ids": list(document_ids), "stage": stage}
        )
        return len(document_ids)

    async def set_pipeline_documents_stage(
        self,
        pipeline_id,
        document_ids,
        *,
        stage,
        from_stage=None,
        worker_id=None,
        create_missing=False,
    ):
        if not document_ids:
            return 0
        self.set_stage_calls.append(
            {
                "pipeline_id": pipeline_id,
                "doc_ids": list(document_ids),
                "stage": stage,
                "from_stage": from_stage,
                "create_missing": create_missing,
            }
        )
        return len(document_ids)

    async def release_pipeline_documents(
        self, pipeline_id, document_ids, *, from_stage, worker_id
    ):
        if not document_ids:
            return 0
        self.release_calls.append(
            {
                "pipeline_id": pipeline_id,
                "doc_ids": list(document_ids),
                "from_stage": from_stage,
            }
        )
        return len(document_ids)

    async def fail_pipeline_documents(
        self, pipeline_id, document_ids, *, from_stage, worker_id
    ):
        if not document_ids:
            return 0
        self.fail_calls.append(
            {
                "pipeline_id": pipeline_id,
                "doc_ids": list(document_ids),
                "from_stage": from_stage,
            }
        )
        return len(document_ids)

    async def complete_pipeline_documents(
        self, pipeline_id, document_ids, *, from_stage, worker_id
    ):
        if not document_ids:
            return 0
        self.complete_calls.append(
            {
                "pipeline_id": pipeline_id,
                "doc_ids": list(document_ids),
                "from_stage": from_stage,
            }
        )
        return len(document_ids)

    async def get_chunks(self, pipeline_id, document_id):
        return self.chunks_by_doc_id.get(document_id, [])

    async def upsert_vectors(self, namespace, vectors):
        self.upsert_calls.append({"namespace": namespace, "vectors": list(vectors)})

    async def patch_attributes(self, namespace, patches):
        self.patch_calls.append({"namespace": namespace, "patches": list(patches)})


class FakeDatabase:
    def __init__(
        self,
        *,
        allow_reservation: bool = True,
        tag_attrs_by_asin: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.allow_reservation = allow_reservation
        self.tag_attrs_by_asin = tag_attrs_by_asin or {}
        self.replace_calls: list[dict[str, Any]] = []
        self.reserve_calls: list[dict[str, Any]] = []

    async def aggregate_review_tag_attrs(
        self, asin, *, min_count, min_fraction, sample_count
    ):
        default = {"tags": [], "classified_review_count": 0, "tag_threshold": min_count}
        return dict(self.tag_attrs_by_asin.get(asin, default))

    async def replace_review_classification(self, *, asin, review_id, tags):
        self.replace_calls.append(
            {"asin": asin, "review_id": review_id, "tags": list(tags)}
        )

    async def try_reserve_review_classification(
        self, *, usage_date, review_count, daily_review_limit
    ):
        self.reserve_calls.append(
            {
                "usage_date": usage_date,
                "review_count": review_count,
                "limit": daily_review_limit,
            }
        )
        return self.allow_reservation


class FakeClipImageEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[Path]] = []
        self.raise_on_call = False

    def encode_image_paths(self, paths):
        self.calls.append(list(paths))
        if self.raise_on_call:
            raise RuntimeError("CLIP failure")
        return [[float(i), 0.0, 1.0] for i in range(len(paths))]


class FakeQwenTextEmbedder:
    def __init__(self) -> None:
        self.chunk_calls: list[str] = []
        self.encode_calls: list[list[str]] = []
        self.raise_on_encode = False

    def chunk_text(self, text, *, chunk_tokens, chunk_overlap):
        self.chunk_calls.append(text)
        if not text.strip():
            return []
        return [text]

    def encode_texts(self, texts):
        self.encode_calls.append(list(texts))
        if self.raise_on_encode:
            raise RuntimeError("Qwen failure")
        return [[float(i), 0.5] for i in range(len(texts))]


class FakeClassifier:
    def __init__(self, response: dict[str, list[ReviewTag]] | None = None) -> None:
        self.response = response or {}
        self.calls: list[list[Any]] = []
        self.raise_on_call = False

    async def close(self) -> None:
        pass

    async def classify(self, reviews):
        self.calls.append(list(reviews))
        if self.raise_on_call:
            raise RuntimeError("OpenRouter failure")
        return dict(self.response)


def make_settings(**overrides) -> SimpleNamespace:
    s = SimpleNamespace(
        resolved_worker_id="test-worker",
        namespace="amazon-products",
        default_pipeline_id="amazon-products-images",
        reviews_pipeline_id="hev-shop-reviews",
        review_aggregate_pipeline_id="amazon-products-review-tags",
        reviews_namespace_base="amazon-reviews",
        reviews_namespace_shard_count=4,
        distance_metric="cosine_distance",
        embedding_claim_size=10,
        claim_lease_seconds=900,
        claim_heartbeat_seconds=3600,  # large → heartbeat task sleeps, never fires
        embedding_batch_size=16,
        vector_upsert_batch_size=10_000,
        chunk_fetch_concurrency=4,
        cleanup_embedded_images=False,
        worker_poll_seconds=5.0,
        review_tag_min_count=3,
        review_tag_min_fraction=0.05,
        review_tag_sample_count=3,
        review_chunk_tokens=64,
        review_chunk_overlap=8,
        review_embedding_batch_size=4,
        review_classification_batch_size=4,
        review_classification_daily_review_limit=100,
        review_aggregate_batch_size=10,
        openrouter_api_key="test-key",
    )
    for key, value in overrides.items():
        setattr(s, key, value)
    return s
