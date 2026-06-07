"""Test doubles for the indexer product pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from hevlayer import (
    ClaimDocumentsRequest,
    ClaimDocumentsResponse,
    Chunk,
    CreatePipelineRequest,
    DocumentsStageResponse,
    HeartbeatDocumentsRequest,
    LayerPerf,
    LayerResponse,
    Pipeline,
    PutChunksRequest,
    PutVectorsRequest,
    StageDocumentResponse,
    StatusResponse,
)


def _attach_perf(data: Any, with_perf: bool) -> Any:
    if not with_perf:
        return data
    return LayerResponse(data=data, perf=LayerPerf(latency_ms=0.0, cache_status=None))


class FakeLayerClient:
    def __init__(self) -> None:
        self.next_claim: list[str] = []
        self.chunks_by_doc_id: dict[str, list[dict[str, Any]]] = {}
        self.raise_on_get_chunks = False

        self.create_pipeline_calls: list[tuple[str, str, str]] = []
        self.claim_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self.fail_calls: list[dict[str, Any]] = []
        self.release_calls: list[dict[str, Any]] = []
        self.heartbeat_calls: list[dict[str, Any]] = []
        self.stage_document_calls: list[dict[str, Any]] = []
        self.pipeline_vector_calls: list[dict[str, Any]] = []

    async def ensure_pipeline(self, body: CreatePipelineRequest | dict[str, Any]) -> Pipeline:
        if isinstance(body, CreatePipelineRequest):
            pid = body.id
            ns = body.target_namespace
            metric = body.distance_metric or "cosine_distance"
        else:
            pid = body["id"]
            ns = body["target_namespace"]
            metric = body.get("distance_metric") or "cosine_distance"
        self.create_pipeline_calls.append((pid, ns, metric))
        return Pipeline(
            id=pid,
            target_namespace=ns,
            distance_metric=metric,
            created_at="2026-05-20T00:00:00Z",
        )

    async def claim_documents(
        self,
        pipeline_id: str,
        body: ClaimDocumentsRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> ClaimDocumentsResponse | LayerResponse[ClaimDocumentsResponse]:
        if isinstance(body, ClaimDocumentsRequest):
            stage = body.stage
            claim_stage = body.claim_stage
            limit = body.limit
            worker_id = body.worker_id
            lease_seconds = body.lease_seconds
            prefix = body.document_id_prefix
        else:
            stage = body.get("stage")
            claim_stage = body.get("claim_stage")
            limit = body.get("limit")
            worker_id = body.get("worker_id")
            lease_seconds = body.get("lease_seconds")
            prefix = body.get("document_id_prefix")
        self.claim_calls.append(
            {
                "pipeline_id": pipeline_id,
                "stage": stage,
                "claim_stage": claim_stage,
                "limit": limit,
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
                "prefix": prefix,
            }
        )
        n = limit if isinstance(limit, int) and limit > 0 else len(self.next_claim)
        head, self.next_claim = self.next_claim[:n], self.next_claim[n:]
        response = ClaimDocumentsResponse(
            pipeline_id=pipeline_id,
            stage=stage or "pending",
            claim_stage=claim_stage or "embedding",
            worker_id=worker_id or "test-worker",
            documents=list(head),
        )
        return _attach_perf(response, with_perf)

    async def heartbeat_documents(
        self,
        pipeline_id: str,
        body: HeartbeatDocumentsRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> DocumentsStageResponse | LayerResponse[DocumentsStageResponse]:
        if isinstance(body, HeartbeatDocumentsRequest):
            doc_ids = list(body.document_ids)
            stage = body.stage
        else:
            doc_ids = list(body["document_ids"])
            stage = body.get("stage")
        if doc_ids:
            self.heartbeat_calls.append(
                {"pipeline_id": pipeline_id, "doc_ids": doc_ids, "stage": stage}
            )
        return _attach_perf(
            DocumentsStageResponse(
                pipeline_id=pipeline_id,
                stage=stage or "pending",
                updated=len(doc_ids),
            ),
            with_perf,
        )

    async def release_documents(
        self,
        pipeline_id: str,
        document_ids: list[str],
        *,
        from_stage: str | None = None,
        worker_id: str | None = None,
        with_perf: bool = False,
    ) -> DocumentsStageResponse | LayerResponse[DocumentsStageResponse]:
        doc_ids = list(document_ids)
        if doc_ids:
            self.release_calls.append(
                {"pipeline_id": pipeline_id, "doc_ids": doc_ids, "from_stage": from_stage}
            )
        return _attach_perf(
            DocumentsStageResponse(
                pipeline_id=pipeline_id, stage="pending", updated=len(doc_ids)
            ),
            with_perf,
        )

    async def fail_documents(
        self,
        pipeline_id: str,
        document_ids: list[str],
        *,
        from_stage: str | None = None,
        worker_id: str | None = None,
        with_perf: bool = False,
    ) -> DocumentsStageResponse | LayerResponse[DocumentsStageResponse]:
        doc_ids = list(document_ids)
        if doc_ids:
            self.fail_calls.append(
                {"pipeline_id": pipeline_id, "doc_ids": doc_ids, "from_stage": from_stage}
            )
        return _attach_perf(
            DocumentsStageResponse(
                pipeline_id=pipeline_id, stage="failed", updated=len(doc_ids)
            ),
            with_perf,
        )

    async def complete_documents(
        self,
        pipeline_id: str,
        document_ids: list[str],
        *,
        from_stage: str | None = None,
        worker_id: str | None = None,
        with_perf: bool = False,
    ) -> DocumentsStageResponse | LayerResponse[DocumentsStageResponse]:
        doc_ids = list(document_ids)
        if doc_ids:
            self.complete_calls.append(
                {"pipeline_id": pipeline_id, "doc_ids": doc_ids, "from_stage": from_stage}
            )
        return _attach_perf(
            DocumentsStageResponse(
                pipeline_id=pipeline_id, stage="indexed", updated=len(doc_ids)
            ),
            with_perf,
        )

    async def get_pipeline_document_chunks(
        self, pipeline_id: str, doc_id: str, *, with_perf: bool = False
    ) -> list[Chunk] | LayerResponse[list[Chunk]]:
        if self.raise_on_get_chunks:
            raise RuntimeError("chunk fetch failed")
        raw = self.chunks_by_doc_id.get(doc_id, [])
        chunks = [
            Chunk(id=c["id"], text=c.get("text"), metadata=c.get("metadata"))
            for c in raw
        ]
        return _attach_perf(chunks, with_perf)

    async def put_pipeline_document_chunks(
        self,
        pipeline_id: str,
        doc_id: str,
        body: PutChunksRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> StageDocumentResponse | LayerResponse[StageDocumentResponse]:
        chunks_in = body.chunks if isinstance(body, PutChunksRequest) else body["chunks"]
        chunk_dicts: list[dict[str, Any]] = []
        for chunk in chunks_in:
            if isinstance(chunk, Chunk):
                chunk_dicts.append(
                    {"id": chunk.id, "text": chunk.text, "metadata": chunk.metadata}
                )
            else:
                chunk_dicts.append(dict(chunk))
        self.stage_document_calls.append(
            {
                "pipeline_id": pipeline_id,
                "document_id": doc_id,
                "chunks": chunk_dicts,
            }
        )
        self.chunks_by_doc_id[doc_id] = chunk_dicts
        return _attach_perf(
            StageDocumentResponse(
                pipeline_id=pipeline_id,
                document_id=doc_id,
                stage="pending",
                chunk_count=len(chunk_dicts),
                chunk_ids=[c["id"] for c in chunk_dicts],
            ),
            with_perf,
        )

    async def put_pipeline_document_vectors(
        self,
        pipeline_id: str,
        doc_id: str,
        body: PutVectorsRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> StatusResponse | LayerResponse[StatusResponse]:
        vectors_in = body.vectors if isinstance(body, PutVectorsRequest) else body["vectors"]
        vector_dicts: list[dict[str, Any]] = []
        for vector in vectors_in:
            if hasattr(vector, "model_dump"):
                vector_dicts.append(vector.model_dump(exclude_none=True))
            else:
                vector_dicts.append(dict(vector))
        self.pipeline_vector_calls.append(
            {"pipeline_id": pipeline_id, "document_id": doc_id, "vectors": vector_dicts}
        )
        return _attach_perf(StatusResponse(status="ok"), with_perf)


class FakeClipImageEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[bytes]] = []
        self.raise_on_call = False

    def encode_image_bytes(self, images: list[bytes]) -> list[list[float]]:
        self.calls.append(list(images))
        if self.raise_on_call:
            raise RuntimeError("CLIP failure")
        return [[float(i), 0.0, 1.0] for i in range(len(images))]


def make_settings(**overrides) -> SimpleNamespace:
    settings = SimpleNamespace(
        resolved_worker_id="test-worker",
        namespace="amazon-products",
        default_pipeline_id="hev-shop-product-images",
        extraction_pipeline_id="hev-shop-extraction-jobs",
        distance_metric="cosine_distance",
        embedding_claim_size=10,
        claim_lease_seconds=900,
        claim_heartbeat_seconds=3600,
        embedding_batch_size=16,
        worker_poll_seconds=0.01,
        http_timeout_seconds=1.0,
        extraction_concurrency=4,
        default_category="Electronics",
        extraction_job_size=10_000,
        hf_dataset="repo",
        hf_token=None,
        dataset_cache_dir=None,
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings
