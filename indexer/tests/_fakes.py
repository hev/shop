"""Shared test doubles for the indexer worker / pipeline contracts.

Lives outside the `test_*.py` collection pattern so pytest doesn't try
to run it. Both `test_workers_characterization.py` (phase-0) and
`test_pipeline.py` (phase-1) import from here.

`FakeLayerClient` duck-types the slice of `hevlayer.HevlayerProtocol`
that the indexer actually exercises. Each call is recorded into flat
dicts so tests can assert payload fields without unwrapping Pydantic
models. Empty-list short-circuits mirror the SDK helpers in
`AsyncHevlayer`: those calls never become HTTP requests in production,
so they shouldn't show up as recorded calls in tests either.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevlayer import (
    ClaimDocumentsRequest,
    ClaimDocumentsResponse,
    CountRequest,
    CountResponse,
    CreateListingRequest,
    CreatePipelineRequest,
    Chunk,
    Document,
    DocumentsStageResponse,
    FetchDocumentsRequest,
    FetchDocumentsResponse,
    HeartbeatDocumentsRequest,
    LayerPerf,
    LayerResponse,
    ListingJob,
    ListingResults,
    PatchRequest,
    Pipeline,
    PutChunksRequest,
    QueryRequest,
    QueryResponse,
    QueryResult,
    SetDocumentsStageRequest,
    StageDocumentResponse,
    StatusResponse,
    UpsertRequest,
)

from app.classifier import ReviewTag


def _attach_perf(data: Any, with_perf: bool) -> Any:
    if not with_perf:
        return data
    return LayerResponse(data=data, perf=LayerPerf(latency_ms=0.0, cache_status=None))


class FakeLayerClient:
    """Records every call; returns scripted claims/chunks."""

    def __init__(self) -> None:
        self.next_claim: list[str] = []
        self.chunks_by_doc_id: dict[str, list[dict[str, Any]]] = {}
        self.documents_by_namespace: dict[tuple[str, str], dict[str, Any]] = {}
        self.listing_results_by_namespace: dict[str, list[dict[str, Any]]] = {}
        self.listing_filters_by_id: dict[str, Any] = {}

        self.create_pipeline_calls: list[tuple[str, str, str]] = []
        self.claim_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self.fail_calls: list[dict[str, Any]] = []
        self.release_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.patch_calls: list[dict[str, Any]] = []
        self.heartbeat_calls: list[dict[str, Any]] = []
        self.set_stage_calls: list[dict[str, Any]] = []
        self.listing_calls: list[dict[str, Any]] = []
        self.stage_document_calls: list[dict[str, Any]] = []
        self.query_calls: list[dict[str, Any]] = []
        self.count_calls: list[dict[str, Any]] = []
        # Scripted responses for query_namespace / count_ranked. When None,
        # the fake returns a sensible default (empty results / count=0).
        self.next_query_response: QueryResponse | None = None
        self.next_count_response: CountResponse | None = None
        self.count_raises: bool = False

    async def ensure_pipeline(self, body: CreatePipelineRequest | dict[str, Any]) -> Pipeline:
        if isinstance(body, CreatePipelineRequest):
            pid, ns, metric = body.id, body.target_namespace, body.distance_metric or "cosine_distance"
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
            limit = body.limit
            worker_id = body.worker_id
            lease_seconds = body.lease_seconds
            claim_stage = body.claim_stage
            prefix = body.document_id_prefix
        else:
            limit = body.get("limit")
            worker_id = body.get("worker_id")
            lease_seconds = body.get("lease_seconds")
            claim_stage = body.get("claim_stage")
            prefix = body.get("document_id_prefix")
        self.claim_calls.append(
            {
                "pipeline_id": pipeline_id,
                "limit": limit,
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
                "claim_stage": claim_stage,
                "prefix": prefix,
            }
        )
        n = limit if isinstance(limit, int) and limit > 0 else len(self.next_claim)
        head, self.next_claim = self.next_claim[:n], self.next_claim[n:]
        response = ClaimDocumentsResponse(
            pipeline_id=pipeline_id,
            stage="pending",
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
        if not doc_ids:
            return _attach_perf(
                DocumentsStageResponse(pipeline_id=pipeline_id, stage=stage or "pending", updated=0),
                with_perf,
            )
        self.heartbeat_calls.append(
            {"pipeline_id": pipeline_id, "doc_ids": doc_ids, "stage": stage}
        )
        return _attach_perf(
            DocumentsStageResponse(pipeline_id=pipeline_id, stage=stage or "pending", updated=len(doc_ids)),
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
            from_stage = body.from_stage
            create_missing = bool(body.create_missing)
        else:
            doc_ids = list(body["document_ids"])
            stage = body["stage"]
            from_stage = body.get("from_stage")
            create_missing = bool(body.get("create_missing", False))
        if not doc_ids:
            return _attach_perf(
                DocumentsStageResponse(pipeline_id=pipeline_id, stage=stage, updated=0),
                with_perf,
            )
        self.set_stage_calls.append(
            {
                "pipeline_id": pipeline_id,
                "doc_ids": doc_ids,
                "stage": stage,
                "from_stage": from_stage,
                "create_missing": create_missing,
            }
        )
        return _attach_perf(
            DocumentsStageResponse(pipeline_id=pipeline_id, stage=stage, updated=len(doc_ids)),
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
        if not doc_ids:
            return _attach_perf(
                DocumentsStageResponse(pipeline_id=pipeline_id, stage="pending", updated=0),
                with_perf,
            )
        self.release_calls.append(
            {"pipeline_id": pipeline_id, "doc_ids": doc_ids, "from_stage": from_stage}
        )
        return _attach_perf(
            DocumentsStageResponse(pipeline_id=pipeline_id, stage="pending", updated=len(doc_ids)),
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
        if not doc_ids:
            return _attach_perf(
                DocumentsStageResponse(pipeline_id=pipeline_id, stage="failed", updated=0),
                with_perf,
            )
        self.fail_calls.append(
            {"pipeline_id": pipeline_id, "doc_ids": doc_ids, "from_stage": from_stage}
        )
        return _attach_perf(
            DocumentsStageResponse(pipeline_id=pipeline_id, stage="failed", updated=len(doc_ids)),
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
        if not doc_ids:
            return _attach_perf(
                DocumentsStageResponse(pipeline_id=pipeline_id, stage="indexed", updated=0),
                with_perf,
            )
        self.complete_calls.append(
            {"pipeline_id": pipeline_id, "doc_ids": doc_ids, "from_stage": from_stage}
        )
        return _attach_perf(
            DocumentsStageResponse(pipeline_id=pipeline_id, stage="indexed", updated=len(doc_ids)),
            with_perf,
        )

    async def get_pipeline_document_chunks(
        self, pipeline_id: str, doc_id: str, *, with_perf: bool = False
    ) -> list[Chunk] | LayerResponse[list[Chunk]]:
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
        for c in chunks_in:
            if isinstance(c, Chunk):
                chunk_dicts.append({"id": c.id, "text": c.text, "metadata": c.metadata})
            else:
                chunk_dicts.append(dict(c))
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

    async def fetch_document(
        self,
        namespace: str,
        doc_id: str,
        *,
        include_attributes: list[str] | None = None,
        with_perf: bool = False,
    ) -> Document | LayerResponse[Document]:
        key = (namespace, doc_id)
        if key not in self.documents_by_namespace:
            raise RuntimeError("not found")
        record = self.documents_by_namespace[key]
        document = Document(id=doc_id, attributes=record.get("attributes") or {})
        return _attach_perf(document, with_perf)

    async def fetch_documents(
        self,
        namespace: str,
        body: FetchDocumentsRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> FetchDocumentsResponse | LayerResponse[FetchDocumentsResponse]:
        if isinstance(body, FetchDocumentsRequest):
            ids = list(body.ids)
        else:
            ids = list(body.get("ids") or [])
        documents: list[Document] = []
        missing: list[str] = []
        for doc_id in ids:
            row = self._find_document_row(namespace, doc_id)
            if row is None:
                missing.append(doc_id)
                continue
            documents.append(Document(id=doc_id, attributes=dict(row.get("attributes") or row)))
        response = FetchDocumentsResponse(documents=documents, missing=missing)
        return _attach_perf(response, with_perf)

    async def upsert_documents(
        self,
        namespace: str,
        body: UpsertRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> StatusResponse | LayerResponse[StatusResponse]:
        if isinstance(body, UpsertRequest):
            upserts = body.upserts or []
        else:
            upserts = body.get("upserts") or []
        vector_dicts: list[dict[str, Any]] = []
        for u in upserts:
            if hasattr(u, "model_dump"):
                vector_dicts.append(u.model_dump(exclude_none=True))
            else:
                vector_dicts.append(dict(u))
        self.upsert_calls.append({"namespace": namespace, "vectors": vector_dicts})
        return _attach_perf(StatusResponse(status="ok"), with_perf)

    async def patch_documents(
        self,
        namespace: str,
        body: PatchRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> StatusResponse | LayerResponse[StatusResponse]:
        if isinstance(body, PatchRequest):
            patches = body.patches or []
        else:
            patches = body.get("patches") or []
        patch_dicts: list[dict[str, Any]] = []
        for p in patches:
            if hasattr(p, "model_dump"):
                patch_dicts.append(p.model_dump(exclude_none=True))
            else:
                patch_dicts.append(dict(p))
        self.patch_calls.append({"namespace": namespace, "patches": patch_dicts})
        for patch in patch_dicts:
            key = (namespace, patch["id"])
            doc = self.documents_by_namespace.setdefault(key, {"attributes": {}})
            attrs = doc.setdefault("attributes", {})
            attrs.update(patch.get("attributes") or {})
        return _attach_perf(StatusResponse(status="ok"), with_perf)

    async def query_namespace(
        self,
        namespace: str,
        body: QueryRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> QueryResponse | LayerResponse[QueryResponse]:
        if isinstance(body, QueryRequest):
            # cursor is a real field on QueryRequest in current SDK versions;
            # older SDKs accepted it via extra=allow and surfaced it in
            # model_extra. Read both for forward/back compatibility.
            extra = body.model_extra or {}
            cursor = getattr(body, "cursor", None) or extra.get("cursor")
            payload = {
                "namespace": namespace,
                "vector": list(body.vector),
                "top_k": body.top_k,
                "filters": body.filters,
                "include_attributes": body.include_attributes,
                "cursor": cursor,
            }
        else:
            payload = {
                "namespace": namespace,
                "vector": list(body.get("vector") or []),
                "top_k": body.get("top_k"),
                "filters": body.get("filters"),
                "include_attributes": body.get("include_attributes"),
                "cursor": body.get("cursor"),
            }
        self.query_calls.append(payload)
        response = self.next_query_response or QueryResponse(
            results=[], stable_as_of=None
        )
        return _attach_perf(response, with_perf)

    async def count_ranked(
        self,
        namespace: str,
        body: CountRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> CountResponse | LayerResponse[CountResponse]:
        if self.count_raises:
            raise RuntimeError("count upstream failure")
        if isinstance(body, CountRequest):
            query = body.query.model_dump(exclude_none=True)
            filters = body.filters
            mode = body.mode
        else:
            query = dict(body.get("query") or {})
            filters = body.get("filters")
            mode = body.get("mode")
        self.count_calls.append(
            {
                "namespace": namespace,
                "query": query,
                "filters": filters,
                "mode": mode,
            }
        )
        response = self.next_count_response or CountResponse(
            count=0,
            bounded=False,
            timed_out=False,
            shards_saturated=0,
            shards_total=1,
            elapsed_ms=0,
        )
        return _attach_perf(response, with_perf)

    async def listing(
        self,
        namespace: str,
        body: CreateListingRequest | dict[str, Any],
        *,
        initial_delay: float = 0.05,
        max_delay: float = 2.0,
        timeout: float | None = None,
    ) -> ListingJob:
        if isinstance(body, CreateListingRequest):
            filters = body.filters
            page_size = body.page_size
        else:
            filters = body.get("filters")
            page_size = body.get("page_size")
        self.listing_calls.append(
            {
                "namespace": namespace,
                "filters": filters,
                "page_size": page_size,
            }
        )
        listing_id = f"listing-{len(self.listing_calls)}"
        self.listing_filters_by_id[listing_id] = filters
        return ListingJob(
            id=listing_id,
            namespace=namespace,
            source="auto",
            effective_source="cache",
            status="completed",
            progress=1.0,
            documents_scanned=0,
            created_at="2026-05-20T00:00:00Z",
            completed_at="2026-05-20T00:00:00Z",
            error=None,
        )

    async def get_listing_results(
        self,
        namespace: str,
        listing_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
        with_perf: bool = False,
    ) -> ListingResults | LayerResponse[ListingResults]:
        rows = self._listing_rows(namespace, listing_id)
        total = len(rows)
        start = offset or 0
        end = start + limit if limit is not None else total
        ids = [self._row_doc_id(row, idx) for idx, row in enumerate(rows[start:end], start)]
        return _attach_perf(ListingResults(ids=ids, total=total), with_perf)

    def _listing_rows(self, namespace: str, listing_id: str) -> list[dict[str, Any]]:
        rows = list(self.listing_results_by_namespace.get(namespace, []))
        filters = self.listing_filters_by_id.get(listing_id)
        if isinstance(filters, list) and len(filters) == 3 and filters[1] == "Eq":
            field, _op, expected = filters
            rows = [
                row
                for row in rows
                if (row.get("attributes") or row).get(field) == expected
            ]
        return rows

    def _find_document_row(self, namespace: str, doc_id: str) -> dict[str, Any] | None:
        key = (namespace, doc_id)
        if key in self.documents_by_namespace:
            return self.documents_by_namespace[key]
        for idx, row in enumerate(self.listing_results_by_namespace.get(namespace, [])):
            if self._row_doc_id(row, idx) == doc_id:
                return row
        return None

    @staticmethod
    def _row_doc_id(row: dict[str, Any], index: int) -> str:
        attrs = row.get("attributes") or row
        for key in ("id", "document_id"):
            value = row.get(key) or attrs.get(key)
            if value:
                return str(value)
        review_id = attrs.get("review_id")
        if review_id:
            return f"{review_id}:chunk:0000"
        return f"doc-{index}"


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
        default_pipeline_id="hev-shop-product-images",
        extraction_pipeline_id="hev-shop-extraction-jobs",
        reviews_pipeline_id="hev-shop-reviews",
        review_aggregate_pipeline_id="hev-shop-review-tags",
        reviews_namespace_base="amazon-reviews",
        reviews_namespace_shard_count=4,
        distance_metric="cosine_distance",
        embedding_claim_size=10,
        claim_lease_seconds=900,
        claim_heartbeat_seconds=3600,  # large → heartbeat task sleeps, never fires
        embedding_batch_size=16,
        vector_upsert_batch_size=10_000,
        review_aggregate_listing_page_size=10_000,
        chunk_fetch_concurrency=4,
        review_upsert_concurrency=4,
        cleanup_embedded_images=False,
        worker_poll_seconds=5.0,
        review_tag_min_count=3,
        review_tag_min_fraction=0.05,
        review_tag_sample_count=3,
        review_chunk_tokens=64,
        review_chunk_overlap=8,
        review_embedding_batch_size=4,
        review_classification_batch_size=4,
        review_aggregate_batch_size=10,
        openrouter_api_key="test-key",
        blob_max_bytes=512 * 1024,
        layer_gateway_public_url="https://aws-us-east-1.hevlayer.com",
    )
    for key, value in overrides.items():
        setattr(s, key, value)
    return s
