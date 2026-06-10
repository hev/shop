"""Endpoint tests for GET /search/trending."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import app
from tests._fakes import FakeLayerClient, make_settings


@pytest.fixture
def client_with_fakes():
    layer = FakeLayerClient()
    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
    }
    app.state.settings = make_settings()
    app.state.layer = layer

    client = TestClient(app)
    try:
        yield client, layer
    finally:
        for key, value in prev.items():
            setattr(app.state, key, value)


class TestTrendingEndpoint:
    def test_reads_the_trending_namespace(self, client_with_fakes) -> None:
        """Reads settings.resolved_trending_namespace (amazon-products-trending),
        not the product namespace."""
        client, layer = client_with_fakes

        resp = client.get("/search/trending")

        assert resp.status_code == 200
        assert layer.turbopuffer_query_calls[0]["namespace"] == (
            "amazon-products-trending"
        )
        assert resp.json()["namespace"] == "amazon-products-trending"

    def test_maps_rows_to_entries_ranked_by_score(self, client_with_fakes) -> None:
        """Returns entries (query/count/score/ndcg) in descending score order."""
        client, layer = client_with_fakes
        layer.next_turbopuffer_query_response = SimpleNamespace(
            rows=[
                {
                    "id": "trend:lamp",
                    "query": "lamp",
                    "count": 2,
                    "score": 2,
                    "ndcg": 0,
                    "sample_top_ids": ["B1"],
                },
                {
                    "id": "trend:headphones",
                    "query": "headphones",
                    "count": 5,
                    "score": 5,
                    "ndcg": 0,
                    "sample_top_ids": ["B2", "B3"],
                },
            ],
            stable_as_of=12345,
        )

        resp = client.get("/search/trending")

        assert resp.status_code == 200
        body = resp.json()
        assert [entry["query"] for entry in body["entries"]] == [
            "headphones",
            "lamp",
        ]
        assert body["entries"][0] == {
            "query": "headphones",
            "count": 5,
            "score": 5.0,
            "ndcg": 0.0,
            "sample_top_ids": ["B2", "B3"],
        }

    def test_respects_limit(self, client_with_fakes) -> None:
        """?limit=N caps the number of entries returned."""
        client, layer = client_with_fakes
        layer.next_turbopuffer_query_response = SimpleNamespace(
            rows=[
                {"query": "a", "count": 3, "score": 3},
                {"query": "b", "count": 2, "score": 2},
                {"query": "c", "count": 1, "score": 1},
            ]
        )

        resp = client.get("/search/trending?limit=2")

        assert resp.status_code == 200
        assert len(resp.json()["entries"]) == 2
        assert layer.turbopuffer_query_calls[0]["body"]["top_k"] == 2

    def test_reports_mode_frequency_when_unweighted(self, client_with_fakes) -> None:
        """mode == 'frequency' so the UI explainer doesn't claim a quality signal."""
        client, _ = client_with_fakes

        resp = client.get("/search/trending")

        assert resp.status_code == 200
        assert resp.json()["mode"] == "frequency"

    def test_empty_namespace_returns_empty_entries_not_error(self, client_with_fakes) -> None:
        """No trending rows yet ⇒ 200 with entries: [] (surface hides client-side)."""
        client, layer = client_with_fakes
        layer.next_turbopuffer_query_response = SimpleNamespace(rows=[])

        resp = client.get("/search/trending")

        assert resp.status_code == 200
        assert resp.json()["entries"] == []
