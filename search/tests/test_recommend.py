"""Endpoint tests for /recommend.

Verifies that the recommend handler:
  - calls layer.query_namespace with nearest_to_id (no vector)
  - applies the [id NotEq <asin>] filter so the seed isn't its own neighbor
  - combines an optional category filter with the seed-exclusion filter
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from hevlayer import QueryResponse, QueryResult

from app.main import app
from tests._fakes import FakeClipTextEmbedder, FakeLayerClient, make_settings


@pytest.fixture
def client_with_fakes():
    layer = FakeLayerClient()
    clip = FakeClipTextEmbedder()
    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
        "text_embedder": app.state.__dict__.get("text_embedder"),
    }
    app.state.settings = make_settings()
    app.state.layer = layer
    app.state.text_embedder = clip

    client = TestClient(app)
    try:
        yield client, layer
    finally:
        for key, value in prev.items():
            setattr(app.state, key, value)


def test_recommend_uses_nearest_to_id_and_excludes_seed(client_with_fakes):
    client, layer = client_with_fakes
    layer.next_query_response = QueryResponse(
        results=[
            QueryResult(
                id="B0002",
                dist=0.12,
                attributes={
                    "asin": "B0002",
                    "title": "Similar product",
                },
            ),
            QueryResult(id="B0003", dist=0.15, attributes={"asin": "B0003"}),
        ],
        stable_as_of=99,
    )

    resp = client.post("/recommend", json={"asin": "B0001", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()

    assert body["asin"] == "B0001"
    assert [hit["id"] for hit in body["hits"]] == ["B0002", "B0003"]
    assert body["hits"][0]["attributes"]["title"] == "Similar product"
    assert body["stable_as_of"] == 99

    call = layer.query_calls[-1]
    assert call["nearest_to_id"] == "B0001"
    assert call["vector"] is None
    assert call["top_k"] == 5
    # Seed-exclusion filter is the sole filter when no category is set.
    assert call["filters"] == ["id", "NotEq", "B0001"]


def test_recommend_with_category_combines_filters(client_with_fakes):
    client, layer = client_with_fakes
    layer.next_query_response = QueryResponse(results=[], stable_as_of=None)

    resp = client.post(
        "/recommend",
        json={"asin": "B0001", "category": "Electronics"},
    )
    assert resp.status_code == 200

    call = layer.query_calls[-1]
    assert call["filters"] == [
        "And",
        [
            ["id", "NotEq", "B0001"],
            ["category", "Eq", "Electronics"],
        ],
    ]


def test_recommend_returns_502_on_upstream_failure(client_with_fakes, monkeypatch):
    client, layer = client_with_fakes

    async def boom(*args, **kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(layer, "query_namespace", boom)
    resp = client.post("/recommend", json={"asin": "B0001"})
    assert resp.status_code == 502
    # Detail is a fixed string — never echo upstream exc text.
    assert resp.json()["detail"] == "recommend upstream failed"
