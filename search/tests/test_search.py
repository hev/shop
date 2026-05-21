"""Endpoint-level tests for /search and /search/reviews.

These exist primarily to lock down the new cursor/count plumbing on the
SearchRequest, /search/reviews query params, and SearchResponse contract.
The handler is exercised through FastAPI's TestClient with a fake layer
client + fake embedders swapped onto app.state, so nothing reaches a real
gateway or model.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from hevlayer import CountResponse, QueryResponse, QueryResult

from app.main import app
from tests._fakes import (
    FakeClipTextEmbedder,
    FakeLayerClient,
    FakeQwenTextEmbedder,
    make_settings,
)


@pytest.fixture
def client_with_fakes():
    layer = FakeLayerClient()
    clip = FakeClipTextEmbedder()
    qwen = FakeQwenTextEmbedder()

    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
        "text_embedder": app.state.__dict__.get("text_embedder"),
        "review_text_embedder": app.state.__dict__.get("review_text_embedder"),
    }
    app.state.settings = make_settings(
        API_REVIEW_SEARCH_ENABLED=True,
        REVIEWS_QUERY_NAMESPACE_BASE="v2-amazon-reviews",
    )
    app.state.layer = layer
    app.state.text_embedder = clip
    app.state.review_text_embedder = qwen

    client = TestClient(app)
    try:
        yield client, layer, clip, qwen
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
    def test_passes_cursor_through_to_query_request(self, client_with_fakes):
        client, layer, _, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"], next_cursor="next-1")

        resp = client.post(
            "/search",
            json={"query": "wireless headphones", "top_k": 5, "cursor": "abc"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_cursor"] == "next-1"
        assert body["count"] is None
        assert layer.query_calls[-1]["cursor"] == "abc"
        assert layer.query_calls[-1]["top_k"] == 5

    def test_omits_next_cursor_when_gateway_returns_short_page(
        self, client_with_fakes
    ):
        client, layer, _, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post("/search", json={"query": "headphones"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_cursor"] is None


class TestSearchCount:
    def test_with_count_fans_out_to_count_ranked(self, client_with_fakes):
        client, layer, _, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001", "B0002"])
        layer.next_count_response = CountResponse(
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
                "tags": ["Overpriced"],
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
        assert count_call["filters"] == [
            "And",
            [
                ["category", "Eq", "Electronics"],
                ["tags", "ContainsAny", ["Overpriced"]],
            ],
        ]

    def test_without_with_count_skips_count_fanout(self, client_with_fakes):
        client, layer, _, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post("/search", json={"query": "headphones"})
        assert resp.status_code == 200
        assert resp.json()["count"] is None
        assert layer.count_calls == []

    def test_count_failure_does_not_fail_the_search(self, client_with_fakes):
        client, layer, _, _ = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])
        layer.count_raises = True

        resp = client.post(
            "/search", json={"query": "headphones", "with_count": True}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] is None
        assert len(body["hits"]) == 1


class TestReviewSearchCursorAndCount:
    def test_cursor_query_param_passes_through(self, client_with_fakes):
        client, layer, _, _ = client_with_fakes
        layer.next_query_response = _query_response(
            ["r1:chunk:0000"], next_cursor="rev-cur"
        )

        resp = client.get(
            "/search/reviews",
            params={
                "asin": "B00FI7TCGI",
                "q": "battery",
                "top_k": 4,
                "cursor": "from-prev-page",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["next_cursor"] == "rev-cur"
        assert layer.query_calls[-1]["cursor"] == "from-prev-page"

    def test_with_count_on_review_search_includes_count(self, client_with_fakes):
        client, layer, _, _ = client_with_fakes
        layer.next_query_response = _query_response(["r1:chunk:0000"])
        layer.next_count_response = CountResponse(
            count=10_000,
            bounded=True,
            timed_out=False,
            shards_saturated=1,
            shards_total=1,
            elapsed_ms=420,
        )

        resp = client.get(
            "/search/reviews",
            params={
                "asin": "B00FI7TCGI",
                "q": "battery",
                "with_count": "true",
                "max_distance": 0.5,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"]["count"] == 10_000
        assert body["count"]["bounded"] is True
        assert body["count"]["max_distance"] == 0.5

        # Filters must include the ASIN gate — without it, count would
        # span the whole shard.
        count_call = layer.count_calls[0]
        assert count_call["filters"] == ["asin", "Eq", "B00FI7TCGI"]
