"""Tests for the result-count → scans migration (RFC 0030)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from hevlayer import QueryResponse, ScanCountResponse

from app import app
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


def _query_response(ids: list[str]) -> QueryResponse:
    return QueryResponse(
        rows=[{"id": i, "$dist": 0.1, "asin": i} for i in ids],
        stable_as_of=12345,
    )


class TestScansMigration:
    def test_with_count_calls_create_scan_in_count_mode(self, client_with_fakes) -> None:
        """The fan-out hits create_scan with mode='count' and ann.radius == max_distance
        (radius is the renamed max_distance), carrying the same filters as the query."""
        client, layer = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])

        resp = client.post(
            "/search",
            json={
                "query": "headphones",
                "with_count": True,
                "max_distance": 0.33,
                "category": "Audio",
            },
        )

        assert resp.status_code == 200
        assert layer.scan_calls == [
            {
                "namespace": "amazon-products",
                "mode": "count",
                "radius": 0.33,
                "vector": [0.1, 0.2, 0.3],
                "filters": ["category", "Eq", "Audio"],
            }
        ]

    def test_count_info_maps_from_scan_count_response(self, client_with_fakes) -> None:
        """count/bounded/timed_out/shards_* map unchanged from ScanCountResponse."""
        client, layer = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])
        layer.next_scan_response = ScanCountResponse(
            count=99,
            served_by="origin",
            bounded=True,
            timed_out=True,
            shards_saturated=2,
            shards_total=8,
            approximate=True,
            elapsed_ms=50,
        )

        resp = client.post("/search", json={"query": "headphones", "with_count": True})

        assert resp.status_code == 200
        assert resp.json()["count"] == {
            "count": 99,
            "bounded": True,
            "timed_out": True,
            "shards_saturated": 2,
            "shards_total": 8,
            "approximate": True,
            "max_distance": 0.4,
            "layer_perf": {"latency_ms": 0, "cache_status": None},
        }

    def test_surfaces_approximate_flag(self, client_with_fakes) -> None:
        """ann counts set CountInfo.approximate=True even when bounded is False."""
        client, layer = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])
        layer.next_scan_response = ScanCountResponse(
            count=7,
            served_by="origin",
            bounded=False,
            timed_out=False,
            shards_saturated=0,
            shards_total=1,
            approximate=True,
            elapsed_ms=5,
        )

        resp = client.post("/search", json={"query": "headphones", "with_count": True})

        assert resp.status_code == 200
        assert resp.json()["count"]["bounded"] is False
        assert resp.json()["count"]["approximate"] is True

    def test_count_failure_still_returns_hits(self, client_with_fakes) -> None:
        """A create_scan failure leaves the search response intact (count=None)."""
        client, layer = client_with_fakes
        layer.next_query_response = _query_response(["B0001"])
        layer.scan_raises = True

        resp = client.post("/search", json={"query": "headphones", "with_count": True})

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] is None
        assert [hit["id"] for hit in body["hits"]] == ["B0001"]
