"""Test doubles for the indexer product pipeline."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

from hevlayer import (
    BlobPutResponse,
    ClaimDocumentsRequest,
    ClaimDocumentsResponse,
    Checkpoint,
    CheckpointList,
    Chunk,
    CreatePipelineRequest,
    Document,
    DocumentsStageResponse,
    HeartbeatDocumentsRequest,
    HevlayerError,
    HintCacheWarmResponse,
    LayerPerf,
    LayerResponse,
    Pipeline,
    PipelineStatus,
    PutChunksRequest,
    PutVectorsRequest,
    SetDocumentsStageRequest,
    StageDocumentResponse,
    StatusResponse,
    WarmBlobsResponse,
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
        self.raise_on_put_blob = False

        self.create_pipeline_calls: list[tuple[str, str, str]] = []
        self.claim_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self.fail_calls: list[dict[str, Any]] = []
        self.release_calls: list[dict[str, Any]] = []
        self.heartbeat_calls: list[dict[str, Any]] = []
        self.stage_document_calls: list[dict[str, Any]] = []
        self.set_stage_calls: list[dict[str, Any]] = []
        self.pipeline_vector_calls: list[dict[str, Any]] = []
        self.put_blob_calls: list[dict[str, Any]] = []
        self.schema_calls: list[dict[str, Any]] = []
        self.checkpoint_calls: list[dict[str, Any]] = []
        self.checkpoints: list[Checkpoint] = []
        self.existing_documents: set[tuple[str, str]] = set()
        self.fetch_document_calls: list[dict[str, Any]] = []
        self.pipeline_statuses: dict[str, PipelineStatus] = {}

        # RFC 0040 trending reduce test doubles (indexer/tests/test_trending.py).
        self.search_history_events: list[Any] = []
        self.clickstream_events: list[Any] = []
        self.list_search_history_calls: list[dict[str, Any]] = []
        self.list_clickstream_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []

        # RFC 0055 blob cache-warm test doubles (indexer/tests/test_warm_blobs.py).
        self.hint_cache_warm_calls: list[dict[str, Any]] = []
        self.warm_blobs_result: WarmBlobsResponse | None = None

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

    async def update_turbopuffer_namespace_schema(
        self, namespace: str, body: dict[str, Any], *, with_perf: bool = False
    ) -> dict[str, Any]:
        self.schema_calls.append(
            {"namespace": namespace, "body": body, "with_perf": with_perf}
        )
        return {"schema": body}

    async def get_pipeline_status(self, pipeline_id: str) -> PipelineStatus:
        return self.pipeline_statuses.get(
            pipeline_id,
            PipelineStatus(
                pipeline_id=pipeline_id,
                counts={},
                pending_count=0,
                processing_count=0,
                failed_count=0,
                indexed_rate_per_min=0.0,
                rate_window_seconds=60,
            ),
        )

    async def create_checkpoint(
        self, namespace: str, body: dict[str, Any], *, with_perf: bool = False
    ) -> Checkpoint | LayerResponse[Checkpoint]:
        label = str(body["label"])
        self.checkpoint_calls.append({"namespace": namespace, "body": dict(body)})
        checkpoint = Checkpoint(
            namespace=namespace,
            label=label,
            watermark_ms=12345,
            sha="abc123",
            row_count=42,
        )
        if not any(existing.label == label for existing in self.checkpoints):
            self.checkpoints.insert(0, checkpoint)
        return _attach_perf(checkpoint, with_perf)

    async def get_checkpoint(
        self, namespace: str, label: str, *, with_perf: bool = False
    ) -> Checkpoint | LayerResponse[Checkpoint]:
        for checkpoint in self.checkpoints:
            if checkpoint.namespace == namespace and checkpoint.label == label:
                return _attach_perf(checkpoint, with_perf)
        raise HevlayerError(404, f"checkpoint {label!r} not found")

    async def list_checkpoints(
        self,
        namespace: str,
        *,
        limit: int | None = None,
        before: str | None = None,
        with_perf: bool = False,
    ) -> CheckpointList | LayerResponse[CheckpointList]:
        checkpoints = [c for c in self.checkpoints if c.namespace == namespace]
        if limit is not None:
            checkpoints = checkpoints[:limit]
        return _attach_perf(
            CheckpointList(checkpoints=checkpoints, next_cursor=None), with_perf
        )

    async def fetch_document(
        self,
        namespace: str,
        doc_id: str,
        *,
        include_attributes: list[str] | None = None,
        with_perf: bool = False,
    ) -> Document | LayerResponse[Document]:
        self.fetch_document_calls.append(
            {
                "namespace": namespace,
                "doc_id": doc_id,
                "include_attributes": include_attributes,
            }
        )
        if (namespace, doc_id) not in self.existing_documents:
            raise HevlayerError(404, f"document {doc_id!r} not found")
        return _attach_perf(Document(id=doc_id, attributes={}), with_perf)

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

    async def set_documents_stage(
        self,
        pipeline_id: str,
        body: SetDocumentsStageRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> DocumentsStageResponse | LayerResponse[DocumentsStageResponse]:
        if isinstance(body, SetDocumentsStageRequest):
            doc_ids = list(body.document_ids)
            stage = body.stage
            create_missing = bool(body.create_missing)
            from_stage = body.from_stage
            worker_id = body.worker_id
        else:
            doc_ids = list(body["document_ids"])
            stage = str(body["stage"])
            create_missing = bool(body.get("create_missing"))
            from_stage = body.get("from_stage")
            worker_id = body.get("worker_id")
        self.set_stage_calls.append(
            {
                "pipeline_id": pipeline_id,
                "doc_ids": doc_ids,
                "stage": stage,
                "create_missing": create_missing,
                "from_stage": from_stage,
                "worker_id": worker_id,
            }
        )
        created = 0
        if create_missing:
            for doc_id in doc_ids:
                if doc_id not in self.chunks_by_doc_id:
                    self.chunks_by_doc_id[doc_id] = []
                    created += 1
            updated = created
        else:
            updated = len(doc_ids)
        return _attach_perf(
            DocumentsStageResponse(
                pipeline_id=pipeline_id, stage=stage, updated=updated
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

    async def put_blob(
        self,
        namespace: str,
        body: bytes,
        *,
        warm: bool | None = None,
        with_perf: bool = False,
    ) -> BlobPutResponse | LayerResponse[BlobPutResponse]:
        if self.raise_on_put_blob:
            raise RuntimeError("blob write failed")
        sha = hashlib.sha256(body).hexdigest()
        self.put_blob_calls.append(
            {
                "namespace": namespace,
                "body": body,
                "warm": warm,
            }
        )
        return _attach_perf(
            BlobPutResponse(ref=f"blob://{namespace}/{sha}", sha256=sha, size=len(body)),
            with_perf,
        )

    async def list_search_history(
        self,
        namespace: str,
        *,
        tags: Any = None,
        from_: Any = None,
        to: Any = None,
        limit: int | None = None,
        with_perf: bool = False,
    ) -> Any:
        """RFC 0040 test double — returns scripted search-history events."""
        self.list_search_history_calls.append(
            {"namespace": namespace, "tags": tags, "from_": from_, "to": to, "limit": limit}
        )
        return _attach_perf(list(self.search_history_events), with_perf)

    async def list_clickstream(
        self,
        namespace: str,
        *,
        trace_id: str | None = None,
        from_: Any = None,
        to: Any = None,
        limit: int | None = None,
        with_perf: bool = False,
    ) -> Any:
        """RFC 0040 test double — returns scripted clickstream events."""
        self.list_clickstream_calls.append(
            {"namespace": namespace, "trace_id": trace_id, "from_": from_, "to": to, "limit": limit}
        )
        return _attach_perf(list(self.clickstream_events), with_perf)

    async def write_namespace(
        self, namespace: str, body: Any, *, with_perf: bool = False
    ) -> Any:
        """Records RFC 0040 trending rows written through RFC 0039's surface."""
        self.upsert_calls.append({"namespace": namespace, "body": body})
        return _attach_perf(SimpleNamespace(status="ok"), with_perf)

    async def hint_cache_warm(
        self,
        namespace: str,
        *,
        turbopuffer: bool | None = None,
        documents: bool | None = None,
        snapshots: bool | None = None,
        blobs: bool | None = None,
        blob_budget_bytes: int | None = None,
        page_size: int | None = None,
        with_perf: bool = False,
    ) -> HintCacheWarmResponse | LayerResponse[HintCacheWarmResponse]:
        """RFC 0055 blob cache-warm test double (indexer/warm_blobs.py)."""
        self.hint_cache_warm_calls.append(
            {
                "namespace": namespace,
                "turbopuffer": turbopuffer,
                "documents": documents,
                "snapshots": snapshots,
                "blobs": blobs,
                "blob_budget_bytes": blob_budget_bytes,
                "page_size": page_size,
            }
        )
        blobs_section = self.warm_blobs_result or WarmBlobsResponse(
            enabled=bool(blobs),
            status="completed",
            attributes=["image_blob"],
            budget_bytes=blob_budget_bytes,
            documents_scanned=0,
            refs_seen=0,
            objects=0,
            bytes=0,
            missing=0,
            invalid_refs=0,
            budget_exhausted=False,
        )
        return _attach_perf(
            HintCacheWarmResponse(namespace=namespace, blobs=blobs_section), with_perf
        )


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
        scheduled_pipeline=False,
        scheduled_refresh_count=10_000,
        scheduled_checkpoint_wait_seconds=0.01,
        scheduled_checkpoint_poll_seconds=0.01,
        hf_dataset="repo",
        hf_token=None,
        dataset_cache_dir=None,
        # RFC 0040 trending reduce knobs (indexer/trending.py).
        trending_quality_weight=0.0,
        trending_min_count=2,
        trending_top_n=12,
        trending_window_hours=24,
        trending_history_tag="page:first",
        trending_interval_seconds=0.01,
        trending_namespace="amazon-products-trending",
        resolved_trending_namespace="amazon-products-trending",
        # RFC 0055 blob cache-warm knobs (indexer/warm_blobs.py).
        blob_warm_budget_bytes=22_000_000_000,
        blob_warm_page_size=1000,
        blob_warm_interval_seconds=0.01,
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings
