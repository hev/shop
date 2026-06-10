"""Endpoint-level tests for /search.

These exist primarily to lock down the cursor/scan-count plumbing on the
SearchRequest and SearchResponse contract. The handler is exercised through
FastAPI's TestClient with a fake layer client + fake embedder swapped onto
app.state, so nothing reaches a real gateway or model.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hevlayer import (
    NamespaceMetadata,
    QueryResponse,
    ScanCountResponse,
)

from app import app
from tests._fakes import (
    FakeClipTextEmbedder,
    FakeLayerClient,
    make_settings,
)


@pytest.fixture
def client_with_fakes():
    layer = FakeLayerClient()
    clip = FakeClipTextEmbedder()

    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
        "text_embedder": app.state.__dict__.get("text_embedder"),
        "meta_cache": app.state.__dict__.get("meta_cache"),
        "meta_cache_lock": app.state.__dict__.get("meta_cache_lock"),
    }
    app.state.settings = make_settings()
    app.state.layer = layer
    app.state.text_embedder = clip
    app.state.meta_cache = {}
    app.state.meta_cache_lock = asyncio.Lock()

    client = TestClient(app)
    try:
        yield client, layer, clip
    finally:
        for key, value in prev.items():
            setattr(app.state, key, value)


def _query_response(ids: list[str], *, next_cursor: str | None = None) -> QueryResponse:
    payload: dict[str, Any] = {
        "rows": [{"id": i, "$dist": 0.1, "asin": i} for i in ids],
        "stable_as_of": 12345,
    }
    if next_cursor is not None:
        payload["next_cursor"] = next_cursor
    return QueryResponse(**payload)


class TestSearchCursor:
    def test_first_page_records_search_history_metadata(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post(
            "/search",
            json={"query": "wireless headphones", "top_k": 5},
            headers={"x-hev-shop-surface": "storefront"},
        )
        assert resp.status_code == 200

        call = layer.query_calls[-1]
        assert call["raw_query"] == "wireless headphones"
        assert set(call["history_tags"]) == {
            "app:hev-shop",
            "surface:storefront",
            "route:search",
            "page:first",
        }

    def test_unmarked_search_does_not_record_storefront_history_metadata(
        self, client_with_fakes
    ):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post("/search", json={"query": "wireless headphones"})
        assert resp.status_code == 200

        call = layer.query_calls[-1]
        assert call["raw_query"] is None
        assert call["history_tags"] is None

    def test_passes_cursor_through_to_query_request(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"], next_cursor="next-1")

        resp = client.post(
            "/search",
            json={"query": "wireless headphones", "top_k": 5, "cursor": "abc"},
            headers={"x-hev-shop-surface": "storefront"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_cursor"] == "next-1"
        assert body["count"] is None
        assert layer.query_calls[-1]["cursor"] == "abc"
        assert layer.query_calls[-1]["top_k"] == 5
        assert layer.query_calls[-1]["raw_query"] is None
        assert layer.query_calls[-1]["history_tags"] is None

    def test_catalog_run_filter_is_sent_to_vector_query(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post(
            "/search",
            json={
                "query": "wireless headphones",
                "catalog_run_id": "catalog-2026-06-09",
            },
        )
        assert resp.status_code == 200

        assert layer.query_calls[-1]["filters"] == [
            "catalog_run_id",
            "Eq",
            "catalog-2026-06-09",
        ]

    def test_omits_next_cursor_when_gateway_returns_short_page(
        self, client_with_fakes
    ):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post("/search", json={"query": "headphones"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_cursor"] is None

    def test_empty_query_requires_catalog_run_id(self, client_with_fakes):
        client, _, _ = client_with_fakes

        resp = client.post("/search", json={"query": ""})

        assert resp.status_code == 422

    def test_empty_query_with_catalog_run_uses_filtered_namespace_query(
        self, client_with_fakes
    ):
        client, layer, clip = client_with_fakes
        layer.next_turbopuffer_query_response = SimpleNamespace(
            rows=[
                {
                    "id": "B0001",
                    "asin": "B0001",
                    "title": "Fresh Camera",
                    "catalog_run_id": "catalog-2026-06-09",
                }
            ],
            stable_as_of=67890,
            next_cursor="drop-page-2",
        )

        resp = client.post(
            "/search",
            json={
                "query": "",
                "top_k": 4,
                "cursor": "drop-page-1",
                "catalog_run_id": "catalog-2026-06-09",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["hits"][0]["id"] == "B0001"
        assert body["stable_as_of"] == 67890
        assert body["next_cursor"] == "drop-page-2"
        assert body["count"] is None
        assert clip.calls == []
        assert layer.query_calls == []
        assert layer.turbopuffer_query_calls[-1] == {
            "namespace": "amazon-products",
            "body": {
                "top_k": 4,
                "include_attributes": True,
                "filters": ["catalog_run_id", "Eq", "catalog-2026-06-09"],
                "cursor": "drop-page-1",
            },
        }


class TestSearchCount:
    def test_with_count_fans_out_to_scan_count(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001", "B0002"])
        layer.next_scan_response = ScanCountResponse(
            count=42,
            served_by="origin",
            bounded=False,
            timed_out=False,
            shards_saturated=0,
            shards_total=4,
            approximate=True,
            elapsed_ms=12,
        )

        resp = client.post(
            "/search",
            json={
                "query": "headphones",
                "with_count": True,
                "max_distance": 0.35,
                "category": "Electronics",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"]["count"] == 42
        assert body["count"]["bounded"] is False
        assert body["count"]["approximate"] is True
        assert body["count"]["max_distance"] == 0.35

        # The count call must see the same filters as the query call so the
        # number actually reflects "matches you'd page through".
        assert len(layer.scan_calls) == 1
        scan_call = layer.scan_calls[0]
        assert scan_call["mode"] == "count"
        assert scan_call["radius"] == 0.35
        assert scan_call["vector"] == [0.1, 0.2, 0.3]
        assert scan_call["filters"] == ["category", "Eq", "Electronics"]

    def test_without_with_count_skips_count_fanout(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post("/search", json={"query": "headphones"})
        assert resp.status_code == 200
        assert resp.json()["count"] is None
        assert layer.scan_calls == []

    def test_count_failure_does_not_fail_the_search(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])
        layer.scan_raises = True

        resp = client.post(
            "/search", json={"query": "headphones", "with_count": True}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] is None
        assert len(body["hits"]) == 1


class TestMeta:
    def test_category_buckets_come_from_snapshot(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.namespace_metadata_data = NamespaceMetadata(
            id="amazon-products",
            schema={},
            approx_logical_bytes=0,
            approx_row_count=12,
            created_at="2026-05-20T00:00:00Z",
            updated_at="2026-05-20T00:00:00Z",
            layer={"stable_as_of": 12345, "is_stable": True},
        )
        layer.snapshot_values_by_namespace["amazon-products"] = {
            "category": [
                {"value": "Audio", "doc_count": 7},
                {"value": "Cameras", "doc_count": 5},
            ]
        }

        resp = client.get("/meta")

        assert resp.status_code == 200
        body = resp.json()
        assert body["vectors"] == 12
        assert body["stable_as_of"] == 12345
        assert body["is_stable"] is True
        assert body["categories"] == [
            {"value": "Audio", "doc_count": 7},
            {"value": "Cameras", "doc_count": 5},
        ]
        assert layer.snapshot_calls[-1] == {
            "namespace": "amazon-products",
            "field": "category",
        }


class TestDrops:
    def test_catalog_run_buckets_come_from_snapshot(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.namespace_metadata_data = NamespaceMetadata(
            id="amazon-products",
            schema={},
            approx_logical_bytes=0,
            approx_row_count=12,
            created_at="2026-05-20T00:00:00Z",
            updated_at="2026-05-20T00:00:00Z",
            layer={"stable_as_of": 12345, "is_stable": True},
        )
        layer.snapshot_watermarks_by_namespace["amazon-products"] = 1780000000000
        layer.snapshot_values_by_namespace["amazon-products"] = {
            "catalog_run_id": [
                {"value": "catalog-2026-06-08", "doc_count": 7},
                {"value": "catalog-2026-06-09", "doc_count": 5},
                {"value": "catalog-2026-06-07", "doc_count": 3},
            ]
        }

        resp = client.get("/drops?limit=2")

        assert resp.status_code == 200
        body = resp.json()
        assert body["namespace"] == "amazon-products"
        assert body["stable_as_of"] == 1780000000000
        assert body["drops"] == [
            {
                "run_id": "catalog-2026-06-09",
                "product_count": 5,
                "stable_as_of": 1780000000000,
            },
            {
                "run_id": "catalog-2026-06-08",
                "product_count": 7,
                "stable_as_of": 1780000000000,
            },
        ]
        assert layer.snapshot_calls[-1] == {
            "namespace": "amazon-products",
            "field": "catalog_run_id",
        }
