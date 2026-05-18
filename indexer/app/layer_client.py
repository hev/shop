from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .records import (
    ProductRecord,
    ReviewRecord,
    review_raw_chunk_id,
    review_work_document_id,
)


@dataclass(frozen=True)
class LayerPerf:
    """Per-request observation for one Layer gateway round-trip.

    `latency_ms` covers the HTTP call only (httpx send → status check),
    so it isolates the gateway round-trip from any FastAPI work this
    process does around it.

    `cache_status` is the gateway's `x-layer-cache` header verbatim:
    `"hit"`, `"miss"`, or `"miss-on-error"` for the degraded path. `None`
    when the gateway didn't attach the header — the `query` endpoint
    routes to turbopuffer and doesn't go through the Aerospike document
    cache, so it never sets the header."""

    latency_ms: int
    cache_status: str | None


class LayerClient:
    def __init__(self, base_url: str, timeout_seconds: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def create_pipeline(
        self, pipeline_id: str, namespace: str, distance_metric: str
    ) -> None:
        response = await self._client.post(
            f"{self.base_url}/v2/pipelines",
            json={
                "id": pipeline_id,
                "target_namespace": namespace,
                "distance_metric": distance_metric,
            },
        )
        if response.status_code == 409:
            return
        response.raise_for_status()

    async def pipeline_status(self, pipeline_id: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.base_url}/v2/pipelines/{pipeline_id}/status"
        )
        response.raise_for_status()
        return response.json()

    async def claim_pipeline_documents(
        self,
        pipeline_id: str,
        *,
        limit: int,
        worker_id: str,
        stage: str = "pending",
        claim_stage: str = "embedding",
        lease_seconds: int = 900,
        document_id_prefix: str | None = None,
    ) -> list[str]:
        payload: dict[str, Any] = {
            "stage": stage,
            "claim_stage": claim_stage,
            "limit": limit,
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
        }
        if document_id_prefix is not None:
            payload["document_id_prefix"] = document_id_prefix
        response = await self._client.post(
            f"{self.base_url}/v2/pipelines/{pipeline_id}/claim",
            json=payload,
        )
        response.raise_for_status()
        return [str(document_id) for document_id in response.json()["documents"]]

    async def heartbeat_pipeline_documents(
        self,
        pipeline_id: str,
        document_ids: list[str],
        *,
        stage: str,
        worker_id: str,
    ) -> int:
        if not document_ids:
            return 0
        response = await self._client.post(
            f"{self.base_url}/v2/pipelines/{pipeline_id}/documents/heartbeat",
            json={
                "document_ids": document_ids,
                "stage": stage,
                "worker_id": worker_id,
            },
        )
        response.raise_for_status()
        return int(response.json()["updated"])

    async def set_pipeline_documents_stage(
        self,
        pipeline_id: str,
        document_ids: list[str],
        *,
        stage: str,
        from_stage: str | None = None,
        worker_id: str | None = None,
        create_missing: bool = False,
    ) -> int:
        if not document_ids:
            return 0
        payload: dict[str, Any] = {
            "document_ids": document_ids,
            "stage": stage,
        }
        if create_missing:
            payload["create_missing"] = True
        if from_stage is not None:
            payload["from_stage"] = from_stage
        if worker_id is not None:
            payload["worker_id"] = worker_id
        response = await self._client.post(
            f"{self.base_url}/v2/pipelines/{pipeline_id}/documents/stage",
            json=payload,
        )
        response.raise_for_status()
        return int(response.json()["updated"])

    async def release_pipeline_documents(
        self,
        pipeline_id: str,
        document_ids: list[str],
        *,
        from_stage: str,
        worker_id: str,
    ) -> int:
        return await self.set_pipeline_documents_stage(
            pipeline_id,
            document_ids,
            stage="pending",
            from_stage=from_stage,
            worker_id=worker_id,
        )

    async def fail_pipeline_documents(
        self,
        pipeline_id: str,
        document_ids: list[str],
        *,
        from_stage: str,
        worker_id: str,
    ) -> int:
        return await self.set_pipeline_documents_stage(
            pipeline_id,
            document_ids,
            stage="failed",
            from_stage=from_stage,
            worker_id=worker_id,
        )

    async def complete_pipeline_documents(
        self,
        pipeline_id: str,
        document_ids: list[str],
        *,
        from_stage: str,
        worker_id: str,
    ) -> int:
        return await self.set_pipeline_documents_stage(
            pipeline_id,
            document_ids,
            stage="indexed",
            from_stage=from_stage,
            worker_id=worker_id,
        )

    async def stage_product(self, pipeline_id: str, product: ProductRecord) -> None:
        response = await self._client.put(
            f"{self.base_url}/v2/pipelines/{pipeline_id}/documents/{product.asin}",
            json={
                "chunks": [
                    {
                        "id": product.asin,
                        "text": product.document_text(),
                        "metadata": product.attributes(),
                    }
                ]
            },
        )
        response.raise_for_status()

    async def stage_review(
        self, pipeline_id: str, review: ReviewRecord, *, work_item: str
    ) -> None:
        if work_item not in {"embed", "classify"}:
            raise ValueError("work_item must be 'embed' or 'classify'")
        response = await self._client.put(
            f"{self.base_url}/v2/pipelines/{pipeline_id}/documents/"
            f"{review_work_document_id(work_item, review.review_id)}",
            json={
                "chunks": [
                    {
                        "id": review_raw_chunk_id(review.review_id),
                        "text": review.document_text(),
                        "metadata": review.attributes(),
                    }
                ]
            },
        )
        response.raise_for_status()

    async def get_chunks(self, pipeline_id: str, document_id: str) -> list[dict[str, Any]]:
        response = await self._client.get(
            f"{self.base_url}/v2/pipelines/{pipeline_id}/documents/{document_id}/chunks"
        )
        response.raise_for_status()
        return response.json()

    async def write_vector(
        self,
        pipeline_id: str,
        document_id: str,
        vector_id: str,
        vector: list[float],
        attributes: dict[str, Any],
    ) -> None:
        response = await self._client.put(
            f"{self.base_url}/v2/pipelines/{pipeline_id}/documents/{document_id}/vectors",
            json={
                "vectors": [
                    {
                        "id": vector_id,
                        "vector": vector,
                        "attributes": attributes,
                    }
                ]
            },
        )
        response.raise_for_status()

    async def upsert_vectors(
        self, namespace: str, vectors: list[dict[str, Any]]
    ) -> None:
        response = await self._client.post(
            f"{self.base_url}/v2/namespaces/{namespace}",
            json={"upserts": vectors},
        )
        response.raise_for_status()

    async def patch_attributes(
        self, namespace: str, patches: list[dict[str, Any]]
    ) -> None:
        """PATCH /v2/namespaces/{namespace} — merge attributes on existing rows.

        Only the keys present in each patch's `attributes` are written; the
        rest of the row is preserved. Vectors cannot be patched (turbopuffer
        constraint). Use for attribute-only updates like the review-tag
        rollup, where the image pipeline already owns title/image_url/etc.
        and a full-record upsert would clobber them."""
        response = await self._client.patch(
            f"{self.base_url}/v2/namespaces/{namespace}",
            json={"patches": patches},
        )
        response.raise_for_status()

    async def fetch_document(
        self,
        namespace: str,
        document_id: str,
        include_attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        body, _perf = await self.fetch_document_with_perf(
            namespace, document_id, include_attributes
        )
        return body

    async def fetch_document_with_perf(
        self,
        namespace: str,
        document_id: str,
        include_attributes: list[str] | None = None,
    ) -> tuple[dict[str, Any], LayerPerf]:
        """Like `fetch_document` but also returns a `LayerPerf` describing
        the round-trip. UI endpoints use this to surface "cache hit · 8ms"
        signals on product pages without obscuring the showcase."""
        params = None
        if include_attributes:
            params = {"include_attributes": ",".join(include_attributes)}
        start = time.monotonic()
        response = await self._client.get(
            f"{self.base_url}/v2/namespaces/{namespace}/documents/{document_id}",
            params=params,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        response.raise_for_status()
        perf = LayerPerf(
            latency_ms=latency_ms,
            cache_status=response.headers.get("x-layer-cache"),
        )
        return response.json(), perf

    async def fetch_many_documents(
        self,
        namespace: str,
        ids: list[str],
        include_attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"{self.base_url}/v2/namespaces/{namespace}/documents",
            json={"ids": ids, "include_attributes": include_attributes},
        )
        response.raise_for_status()
        return response.json()

    async def query_namespace(
        self,
        namespace: str,
        vector: list[float],
        top_k: int,
        include_attributes: list[str] | bool | None = None,
        filters: Any | None = None,
    ) -> dict[str, Any]:
        """Returns the raw QueryResponse body: `{results, stable_as_of?}`.
        `stable_as_of` is the epoch-ms upper bound the gateway applied to
        guarantee the result reflects a fully-indexed view; `None` before the
        consistency watcher has seen a clean snapshot."""
        body, _perf = await self.query_namespace_with_perf(
            namespace, vector, top_k, include_attributes, filters
        )
        return body

    async def query_namespace_with_perf(
        self,
        namespace: str,
        vector: list[float],
        top_k: int,
        include_attributes: list[str] | bool | None = None,
        filters: Any | None = None,
    ) -> tuple[dict[str, Any], LayerPerf]:
        """Like `query_namespace` but also returns a `LayerPerf`. Note:
        queries don't go through the document cache, so `cache_status`
        on the returned perf will be `None`. The latency still isolates
        the gateway+turbopuffer round-trip from any handler-side work."""
        payload: dict[str, Any] = {"vector": vector, "top_k": top_k}
        if include_attributes is not None:
            payload["include_attributes"] = include_attributes
        if filters is not None:
            payload["filters"] = filters
        start = time.monotonic()
        response = await self._client.post(
            f"{self.base_url}/v2/namespaces/{namespace}/query",
            json=payload,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        response.raise_for_status()
        perf = LayerPerf(
            latency_ms=latency_ms,
            cache_status=response.headers.get("x-layer-cache"),
        )
        return response.json(), perf

    # --- Scan ---
    #
    # Scan picks between Aerospike cache and Turbopuffer origin based on a
    # consistency watermark. See docs/guides/namespaces.md ("Scan") for the
    # auto-mode policy and response shape.

    async def create_scan(
        self,
        namespace: str,
        scan_type: str,
        *,
        field: str | None = None,
        source: str | None = None,
        filters: Any | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """Kick off a scan. Returns the initial ScanResponse (status='running')."""
        payload: dict[str, Any] = {"scan_type": scan_type}
        if field is not None:
            payload["field"] = field
        if source is not None:
            payload["source"] = source
        if filters is not None:
            payload["filters"] = filters
        if page_size is not None:
            payload["page_size"] = page_size
        response = await self._client.post(
            f"{self.base_url}/v2/namespaces/{namespace}/scans",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def get_scan(self, namespace: str, scan_id: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.base_url}/v2/namespaces/{namespace}/scans/{scan_id}"
        )
        response.raise_for_status()
        return response.json()

    async def list_scans(self, namespace: str) -> list[dict[str, Any]]:
        response = await self._client.get(
            f"{self.base_url}/v2/namespaces/{namespace}/scans"
        )
        response.raise_for_status()
        return response.json()

    async def get_scan_results(
        self, namespace: str, scan_id: str
    ) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.base_url}/v2/namespaces/{namespace}/scans/{scan_id}/results"
        )
        response.raise_for_status()
        return response.json()

    async def wait_for_scan(
        self,
        namespace: str,
        scan_id: str,
        *,
        poll_interval: float = 1.0,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Poll get_scan until status != 'running'. Polling starts at 50ms
        and backs off exponentially, capped at `poll_interval` seconds, so a
        fast snapshot scan (~100-300ms) is observed quickly while a long
        origin scan still tops out at the configured cadence. Raises
        TimeoutError if `timeout` (seconds) elapses first, or RuntimeError
        if the scan fails."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout if timeout is not None else None
        delay = min(0.05, poll_interval)
        while True:
            scan = await self.get_scan(namespace, scan_id)
            status = scan.get("status")
            if status == "completed":
                return scan
            if status == "failed":
                raise RuntimeError(
                    f"scan {scan_id} failed: {scan.get('error', 'unknown error')}"
                )
            if deadline is not None and loop.time() >= deadline:
                raise TimeoutError(f"scan {scan_id} did not complete in {timeout}s")
            await asyncio.sleep(delay)
            delay = min(delay * 2, poll_interval)

    async def scan(
        self,
        namespace: str,
        scan_type: str,
        *,
        field: str | None = None,
        source: str | None = None,
        filters: Any | None = None,
        page_size: int | None = None,
        poll_interval: float = 1.0,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Convenience: create a scan and wait for it to complete. Returns
        the final ScanResponse with `stable_as_of` and `effective_source`
        populated. For `field_values` scans, fetch results via
        `get_scan_results`."""
        scan = await self.create_scan(
            namespace,
            scan_type,
            field=field,
            source=source,
            filters=filters,
            page_size=page_size,
        )
        return await self.wait_for_scan(
            namespace,
            scan["id"],
            poll_interval=poll_interval,
            timeout=timeout,
        )

    async def fetch_namespace_metadata(self, namespace: str) -> dict[str, Any]:
        """GET /v2/namespaces/{ns}/metadata — turbopuffer's response proxied
        verbatim plus a `layer.{stable_as_of, is_stable}` enhancement block.
        See apps/layer-gateway/docs/guides/namespaces.md → "Namespace metadata"."""
        body, _perf = await self.fetch_namespace_metadata_with_perf(namespace)
        return body

    async def fetch_namespace_metadata_with_perf(
        self, namespace: str
    ) -> tuple[dict[str, Any], LayerPerf]:
        """Like `fetch_namespace_metadata` but also returns a `LayerPerf`."""
        start = time.monotonic()
        response = await self._client.get(
            f"{self.base_url}/v2/namespaces/{namespace}/metadata"
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        response.raise_for_status()
        perf = LayerPerf(
            latency_ms=latency_ms,
            cache_status=response.headers.get("x-layer-cache"),
        )
        return response.json(), perf

    async def warm_namespace(self, namespace: str) -> dict[str, Any]:
        """POST /v2/namespaces/{ns}/warm — kick off a full origin scan that
        also stamps `cache_warmed_through` so subsequent auto-mode scans can
        serve from cache. Returns the running ScanResponse; pair with
        `wait_for_scan` to block until done."""
        response = await self._client.post(
            f"{self.base_url}/v2/namespaces/{namespace}/warm",
        )
        response.raise_for_status()
        return response.json()
