"""Endpoint-level tests for /search.

These exist primarily to lock down the new cursor/result-count plumbing on the
SearchRequest and SearchResponse contract. The handler is exercised through
FastAPI's TestClient with a fake layer client + fake embedder swapped onto
app.state, so nothing reaches a real gateway or model.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hevlayer import (
    ResultCountResponse,
    NamespaceMetadata,
    QueryResponse,
    QueryResult,
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
        "results": [QueryResult(id=i, dist=0.1, attributes={"asin": i}) for i in ids],
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

    def test_omits_next_cursor_when_gateway_returns_short_page(
        self, client_with_fakes
    ):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post("/search", json={"query": "headphones"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_cursor"] is None


class TestSearchCount:
    def test_with_count_fans_out_to_result_count(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001", "B0002"])
        layer.next_count_response = ResultCountResponse(
            count=42,
            bounded=False,
            timed_out=False,
            shards_saturated=0,
            shards_total=4,
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
        assert body["count"]["max_distance"] == 0.35

        # The count call must see the same filters as the query call so the
        # number actually reflects "matches you'd page through".
        assert len(layer.count_calls) == 1
        count_call = layer.count_calls[0]
        assert count_call["query"]["max_distance"] == 0.35
        assert count_call["filters"] == ["category", "Eq", "Electronics"]

    def test_without_with_count_skips_count_fanout(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post("/search", json={"query": "headphones"})
        assert resp.status_code == 200
        assert resp.json()["count"] is None
        assert layer.count_calls == []

    def test_count_failure_does_not_fail_the_search(self, client_with_fakes):
        client, layer, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])
        layer.count_raises = True

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
