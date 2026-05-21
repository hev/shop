"""Test doubles for the search service.

Only the slice of hevlayer that /search, /search/reviews, /product,
/reviews/samples, and /meta actually call lives here. Indexer-only
methods (claim_documents, set_documents_stage, etc.) belong in
`indexer/tests/_fakes.py`.

Recorded calls land in flat dicts so tests can assert on payload fields
without unwrapping pydantic models.
"""

from __future__ import annotations

from typing import Any

from hevlayer import (
    CountRequest,
    CountResponse,
    CreateScanRequest,
    Document,
    LayerPerf,
    LayerResponse,
    QueryRequest,
    QueryResponse,
    QueryResult,
    Scan,
)


def _attach_perf(data: Any, with_perf: bool) -> Any:
    if not with_perf:
        return data
    return LayerResponse(data=data, perf=LayerPerf(latency_ms=0.0, cache_status=None))


class FakeLayerClient:
    """Records every call. Scripted responses via `next_*_response` fields."""

    def __init__(self) -> None:
        self.query_calls: list[dict[str, Any]] = []
        self.count_calls: list[dict[str, Any]] = []
        self.fetch_document_calls: list[dict[str, Any]] = []
        self.scan_calls: list[dict[str, Any]] = []
        self.namespace_metadata_calls: list[str] = []

        self.next_query_response: QueryResponse | None = None
        self.next_count_response: CountResponse | None = None
        self.documents_by_namespace: dict[tuple[str, str], dict[str, Any]] = {}
        self.scan_results_by_namespace: dict[str, list[dict[str, Any]]] = {}
        self.namespace_metadata_data: Any = None
        self.count_raises: bool = False

    async def query_namespace(
        self,
        namespace: str,
        body: QueryRequest | dict[str, Any],
        *,
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
                "include_attributes": body.include_attributes,
                "cursor": cursor,
            }
        else:
            raw_vector = body.get("vector")
            payload = {
                "namespace": namespace,
                "vector": list(raw_vector) if raw_vector is not None else None,
                "nearest_to_id": body.get("nearest_to_id"),
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

    async def scan(
        self,
        namespace: str,
        body: CreateScanRequest | dict[str, Any],
        *,
        initial_delay: float = 0.05,
        max_delay: float = 2.0,
        timeout: float | None = None,
    ) -> Scan:
        if isinstance(body, CreateScanRequest):
            scan_type = body.scan_type
            field = body.field
        else:
            scan_type = body["scan_type"]
            field = body.get("field")
        self.scan_calls.append(
            {
                "namespace": namespace,
                "scan_type": scan_type,
                "field": field,
            }
        )
        scan_id = f"scan-{len(self.scan_calls)}"
        return Scan(
            id=scan_id,
            namespace=namespace,
            scan_type=scan_type,
            source="auto",
            effective_source="cache",
            status="completed",
            progress=1.0,
            documents_scanned=0,
            created_at="2026-05-20T00:00:00Z",
        )

    async def get_scan_results(
        self,
        namespace: str,
        scan_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
        with_perf: bool = False,
    ) -> Any:
        rows = list(self.scan_results_by_namespace.get(namespace, []))
        return _attach_perf({"results": rows, "total": len(rows)}, with_perf)


class FakeClipTextEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def encode_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1, 0.2, 0.3]


class FakeQwenTextEmbedder:
    def __init__(self) -> None:
        self.encode_calls: list[list[str]] = []

    def encode_texts(self, texts: list[str]) -> list[list[float]]:
        self.encode_calls.append(list(texts))
        return [[float(i), 0.5] for i in range(len(texts))]


def make_settings(**overrides):
    """Construct a real `Settings` with overrides. Tests can pass either
    field names (`reviews_query_namespace_base=...`) or env-var aliases
    (`REVIEWS_QUERY_NAMESPACE_BASE=...`)."""
    from hev_shop_common.config import Settings

    return Settings(**overrides)
