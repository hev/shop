from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from hevlayer import HevlayerError, PipelineStatus

from app import app
from tests._fakes import FakeLayerClient, make_settings


class FakeStatusLayer:
    def __init__(
        self,
        statuses: dict[str, PipelineStatus],
        *,
        missing: set[str] | None = None,
    ) -> None:
        self.statuses = statuses
        self.missing = missing or set()

    async def get_pipeline_status(self, pipeline_id: str) -> PipelineStatus:
        if pipeline_id in self.missing:
            raise HevlayerError(404, f"Pipeline '{pipeline_id}' not found")
        return self.statuses[pipeline_id]


@pytest.fixture
def client_with_fakes() -> Iterator[TestClient]:
    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
    }
    extraction_pipeline_id = "hev-shop-extraction-jobs"
    app.state.settings = make_settings(extraction_pipeline_id=extraction_pipeline_id)
    app.state.layer = FakeStatusLayer(
        {
            extraction_pipeline_id: PipelineStatus(
                pipeline_id=extraction_pipeline_id,
                counts={"pending": 3, "embedding": 2},
                pending_count=3,
                processing_count=2,
                failed_count=0,
                indexed_rate_per_min=0.0,
                rate_window_seconds=60,
            )
        },
        missing={"hev-shop-product-images"},
    )

    client = TestClient(app)
    try:
        yield client
    finally:
        for key, value in prev.items():
            setattr(app.state, key, value)


def test_status_returns_empty_layer_state_when_product_pipeline_is_missing(
    client_with_fakes: TestClient,
) -> None:
    response = client_with_fakes.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_id"] == "hev-shop-product-images"
    assert body["layer"] == {
        "pipeline_id": "hev-shop-product-images",
        "counts": {},
        "pending_count": 0,
        "processing_count": 0,
        "failed_count": 0,
        "indexed_rate_per_min": 0.0,
        "rate_window_seconds": 0,
    }
    assert body["jobs"] == {"pending": 3, "embedding": 2}


def test_index_stamps_catalog_run_id_on_extraction_jobs() -> None:
    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
    }
    layer = FakeLayerClient()
    app.state.settings = make_settings(extraction_job_size=2)
    app.state.layer = layer

    client = TestClient(app)
    try:
        response = client.post(
            "/index",
            json={
                "category": "Electronics",
                "count": 3,
                "job_size": 2,
                "catalog_run_id": "catalog-2026-06-09",
            },
        )
    finally:
        for key, value in prev.items():
            setattr(app.state, key, value)

    assert response.status_code == 200
    body = response.json()
    assert body["catalog_run_id"] == "catalog-2026-06-09"
    assert body["jobs_created"] == 2
    assert len(layer.stage_document_calls) == 2
    assert {
        call["chunks"][0]["metadata"]["catalog_run_id"]
        for call in layer.stage_document_calls
    } == {"catalog-2026-06-09"}
