"""Test doubles for the search service.

Only the slice of hevlayer that /search, /product, /recommend, and /meta
actually call lives here. Indexer-only methods (claim_documents,
set_documents_stage, etc.) belong in `indexer/tests/_fakes.py`.

Recorded calls land in flat dicts so tests can assert on payload fields
without unwrapping pydantic models.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from hevlayer import (
    Checkpoint,
    CheckpointList,
    CreateScanRequest,
    CreateSnapshotRequest,
    Document,
    FetchDocumentsResponse,
    LayerPerf,
    LayerResponse,
    QueryRequest,
    QueryResponse,
    SnapshotBody,
    SnapshotField,
    SnapshotJob,
    SnapshotValueCount,
    ScanCountResponse,
    ScanIdsResponse,
    ScanJob,
)


def _attach_perf(data: Any, with_perf: bool) -> Any:
    if not with_perf:
        return data
    return LayerResponse(data=data, perf=LayerPerf(latency_ms=0.0, cache_status=None))


class FakeLayerClient:
    """Records every call. Scripted responses via `next_*_response` fields."""

    def __init__(self) -> None:
        self.query_calls: list[dict[str, Any]] = []
        self.fetch_document_calls: list[dict[str, Any]] = []
        self.fetch_documents_calls: list[dict[str, Any]] = []
        self.snapshot_calls: list[dict[str, Any]] = []
        self.namespace_metadata_calls: list[str] = []

        self.next_query_response: QueryResponse | None = None
        self.documents_by_namespace: dict[tuple[str, str], dict[str, Any]] = {}
        self.snapshot_values_by_namespace: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.snapshot_watermarks_by_namespace: dict[str, int] = {}
        self.checkpoints_by_namespace: dict[str, list[dict[str, Any]]] = {}
        self.checkpoint_calls: list[dict[str, Any]] = []
        self.namespace_metadata_data: Any = None
        self.scan_calls: list[dict[str, Any]] = []
        self.scan_result_calls: list[dict[str, Any]] = []
        self.scan_ids_by_namespace: dict[str, list[str]] = {}
        self.scan_jobs_by_id: dict[str, ScanJob] = {}
        self.next_scan_response: Any = None
        self.next_scan_results_response: ScanIdsResponse | None = None
        self.scan_raises: bool = False
        self.turbopuffer_query_calls: list[dict[str, Any]] = []
        self.next_turbopuffer_query_response: Any = None

    async def query_namespace(
        self,
        namespace: str,
        body: QueryRequest | dict[str, Any],
        *,
        raw_query: str | None = None,
        tags: list[str] | None = None,
        with_perf: bool = False,
    ) -> QueryResponse | LayerResponse[QueryResponse]:
        if isinstance(body, QueryRequest):
            # cursor lives on the request as a typed field in current
            # SDKs and as an extra in older builds — read both.
            extra = body.model_extra or {}
            cursor = getattr(body, "cursor", None) or extra.get("cursor")
            payload = {
                "namespace": namespace,
                "vector": list(body.vector) if body.vector is not None else None,
                "nearest_to_id": body.nearest_to_id,
                "top_k": body.top_k,
                "filters": body.filters,
                "between": body.between,
                "include_attributes": body.include_attributes,
                "cursor": cursor,
                "raw_query": raw_query,
                "history_tags": tags,
            }
        else:
            raw_vector = body.get("vector")
            payload = {
                "namespace": namespace,
                "vector": list(raw_vector) if raw_vector is not None else None,
                "nearest_to_id": body.get("nearest_to_id"),
                "top_k": body.get("top_k"),
                "filters": body.get("filters"),
                "between": body.get("between"),
                "include_attributes": body.get("include_attributes"),
                "cursor": body.get("cursor"),
                "raw_query": raw_query,
                "history_tags": tags,
            }
        self.query_calls.append(payload)
        response = self.next_query_response or QueryResponse(
            rows=[], stable_as_of=None
        )
        return _attach_perf(response, with_perf)

    async def create_scan(
        self,
        namespace: str,
        body: Any,
        *,
        with_perf: bool = False,
    ) -> Any:
        if self.scan_raises:
            raise RuntimeError("scan upstream failure")
        get = body.get if isinstance(body, dict) else (lambda k: getattr(body, k, None))
        ann = get("ann")
        if ann is None:
            radius = None
            vector = None
        elif isinstance(ann, dict):
            radius = ann.get("radius")
            vector = ann.get("vector")
        else:
            radius = getattr(ann, "radius", None)
            vector = getattr(ann, "vector", None)
        self.scan_calls.append(
            {
                "namespace": namespace,
                "mode": get("mode"),
                "source": get("source"),
                "radius": radius,
                "vector": list(vector) if vector is not None else None,
                "filters": get("filters"),
                "between": get("between"),
            }
        )
        if self.next_scan_response is not None:
            response = self.next_scan_response
        elif get("mode") == "ids":
            scan_id = f"scan-{len(self.scan_calls)}"
            response = ScanJob(
                id=scan_id,
                namespace=namespace,
                mode="ids",
                source="auto",
                effective_source="origin",
                status="completed",
                progress=1.0,
                documents_scanned=len(self.scan_ids_by_namespace.get(namespace, [])),
                stable_as_of=2000,
                created_at="2026-05-20T00:00:00Z",
                completed_at="2026-05-20T00:00:00Z",
                error=None,
            )
            self.scan_jobs_by_id[scan_id] = response
        else:
            response = ScanCountResponse(
                count=0,
                bounded=False,
                timed_out=False,
                shards_saturated=0,
                shards_total=1,
                approximate=True,
                served_by="origin",
                elapsed_ms=0,
            )
        return _attach_perf(response, with_perf)

    async def get_scan(
        self,
        namespace: str,
        scan_id: str,
        *,
        with_perf: bool = False,
    ) -> ScanJob | LayerResponse[ScanJob]:
        job = self.scan_jobs_by_id.get(scan_id)
        if job is None:
            job = ScanJob(
                id=scan_id,
                namespace=namespace,
                mode="ids",
                source="auto",
                effective_source="origin",
                status="completed",
                progress=1.0,
                documents_scanned=0,
                stable_as_of=2000,
                created_at="2026-05-20T00:00:00Z",
                completed_at="2026-05-20T00:00:00Z",
                error=None,
            )
        return _attach_perf(job, with_perf)

    async def wait_for_scan(
        self,
        namespace: str,
        scan_id: str,
        *,
        initial_delay: float = 0.05,
        max_delay: float = 2.0,
        timeout: float | None = None,
    ) -> ScanJob:
        return self.scan_jobs_by_id[scan_id]

    async def get_scan_results(
        self,
        namespace: str,
        scan_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
        with_perf: bool = False,
    ) -> ScanIdsResponse | LayerResponse[ScanIdsResponse]:
        self.scan_result_calls.append(
            {
                "namespace": namespace,
                "scan_id": scan_id,
                "limit": limit,
                "offset": offset,
            }
        )
        if self.next_scan_results_response is not None:
            return _attach_perf(self.next_scan_results_response, with_perf)
        ids = self.scan_ids_by_namespace.get(namespace, [])
        start = offset or 0
        end = start + limit if limit is not None else None
        return _attach_perf(
            ScanIdsResponse(ids=ids[start:end], total=len(ids)),
            with_perf,
        )

    async def query_turbopuffer_namespace(
        self,
        namespace: str,
        body: Any,
        *,
        with_perf: bool = False,
    ) -> Any:
        payload = body if isinstance(body, dict) else body.model_dump(exclude_none=True)
        self.turbopuffer_query_calls.append(
            {"namespace": namespace, "body": dict(payload)}
        )
        response = self.next_turbopuffer_query_response or SimpleNamespace(rows=[])
        return _attach_perf(response, with_perf)

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
        key = (namespace, doc_id)
        if key not in self.documents_by_namespace:
            raise RuntimeError("not found")
        record = self.documents_by_namespace[key]
        document = Document(id=doc_id, attributes=record.get("attributes") or {})
        return _attach_perf(document, with_perf)

    async def fetch_documents(
        self,
        namespace: str,
        body: Any,
        *,
        with_perf: bool = False,
    ) -> FetchDocumentsResponse | LayerResponse[FetchDocumentsResponse]:
        ids = list(body.get("ids", []))
        include_attributes = body.get("include_attributes")
        self.fetch_documents_calls.append(
            {
                "namespace": namespace,
                "ids": ids,
                "include_attributes": include_attributes,
            }
        )
        documents: list[Document] = []
        missing: list[str] = []
        for doc_id in ids:
            key = (namespace, doc_id)
            if key not in self.documents_by_namespace:
                missing.append(doc_id)
                continue
            record = self.documents_by_namespace[key]
            documents.append(
                Document(id=doc_id, attributes=record.get("attributes") or {})
            )
        return _attach_perf(
            FetchDocumentsResponse(documents=documents, missing=missing),
            with_perf,
        )

    async def get_namespace_metadata(
        self,
        namespace: str,
        *,
        with_perf: bool = False,
    ) -> Any:
        self.namespace_metadata_calls.append(namespace)
        data = self.namespace_metadata_data
        if data is None:
            raise RuntimeError("no metadata scripted")
        return _attach_perf(data, with_perf)

    async def list_checkpoints(
        self,
        namespace: str,
        *,
        limit: int | None = None,
        before: str | None = None,
        with_perf: bool = False,
    ) -> CheckpointList | LayerResponse[CheckpointList]:
        self.checkpoint_calls.append(
            {"namespace": namespace, "limit": limit, "before": before}
        )
        raw = list(self.checkpoints_by_namespace.get(namespace, []))
        if before:
            for index, checkpoint in enumerate(raw):
                if checkpoint.get("label") == before:
                    raw = raw[index + 1 :]
                    break
        if limit is not None:
            raw = raw[:limit]
        data = CheckpointList(
            checkpoints=[
                Checkpoint(
                    namespace=namespace,
                    label=str(row["label"]),
                    watermark_ms=int(row["watermark_ms"]),
                    sha=str(row.get("sha") or "sha"),
                    row_count=int(row.get("row_count") or 0),
                )
                for row in raw
            ],
            next_cursor=None,
        )
        return _attach_perf(data, with_perf)

    async def create_snapshot(
        self,
        namespace: str,
        body: CreateSnapshotRequest | dict[str, Any],
        *,
        with_perf: bool = False,
    ) -> SnapshotJob | LayerResponse[SnapshotJob]:
        if isinstance(body, CreateSnapshotRequest):
            field = body.field
        else:
            field = body.get("field")
        self.snapshot_calls.append(
            {
                "namespace": namespace,
                "field": field,
            }
        )
        job = SnapshotJob(
            id=f"snapshot-{len(self.snapshot_calls)}",
            namespace=namespace,
            field=field or "",
            source="auto",
            effective_source="cache",
            status="completed",
            progress=1.0,
            documents_scanned=0,
            stable_as_of=None,
            created_at="2026-05-20T00:00:00Z",
            completed_at="2026-05-20T00:00:00Z",
            error=None,
            sha=f"sha-{len(self.snapshot_calls)}",
        )
        return _attach_perf(job, with_perf)

    async def get_snapshot_job(
        self,
        namespace: str,
        job_id: str,
        *,
        with_perf: bool = False,
    ) -> SnapshotJob | LayerResponse[SnapshotJob]:
        index = int(job_id.rsplit("-", 1)[-1])
        call = self.snapshot_calls[index - 1]
        job = SnapshotJob(
            id=job_id,
            namespace=namespace,
            field=call.get("field") or "",
            source="auto",
            effective_source="cache",
            status="completed",
            progress=1.0,
            documents_scanned=0,
            stable_as_of=None,
            created_at="2026-05-20T00:00:00Z",
            completed_at="2026-05-20T00:00:00Z",
            error=None,
            sha=f"sha-{index}",
        )
        return _attach_perf(job, with_perf)

    async def get_namespace_snapshot(
        self,
        namespace: str,
        sha: str,
        *,
        with_perf: bool = False,
    ) -> SnapshotBody | LayerResponse[SnapshotBody]:
        index = int(sha.rsplit("-", 1)[-1])
        field = self.snapshot_calls[index - 1].get("field") or ""
        rows = self.snapshot_values_by_namespace.get(namespace, {}).get(field, [])
        body = SnapshotBody(
            namespace=namespace,
            watermark_ms=self.snapshot_watermarks_by_namespace.get(namespace, 0),
            sha=sha,
            fields=[
                SnapshotField(
                    name=field,
                    values=[
                        SnapshotValueCount(
                            v=str(row["value"]), n=int(row["doc_count"])
                        )
                        for row in rows
                    ],
                )
            ],
            fields_skipped=[],
        )
        return _attach_perf(body, with_perf)


class FakeClipTextEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def encode_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1, 0.2, 0.3]


def make_settings(**overrides):
    """Construct a real `Settings` with overrides."""
    from hev_shop_common.config import Settings

    return Settings(**overrides)
