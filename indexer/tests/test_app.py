from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from hevlayer import HevlayerError, PipelineStatus

from app import amazon_products_namespace_schema, app
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


def test_index_returns_catalog_label_without_stamping_extraction_jobs() -> None:
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
    assert all(
        "catalog_run_id" not in call["chunks"][0]["metadata"]
        for call in layer.stage_document_calls
    )


def test_index_checkpoint_posts_layer_checkpoint_when_pipelines_are_stable() -> None:
    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
    }
    layer = FakeLayerClient()
    app.state.settings = make_settings()
    app.state.layer = layer

    client = TestClient(app)
    try:
        response = client.post(
            "/index/checkpoint",
            json={"catalog_run_id": "catalog-2026-06-09"},
        )
    finally:
        for key, value in prev.items():
            setattr(app.state, key, value)

    assert response.status_code == 200
    body = response.json()
    assert body["catalog_run_id"] == "catalog-2026-06-09"
    assert body["checkpoint"]["label"] == "catalog-2026-06-09"
    assert body["checkpoint"]["watermark_ms"] == 12345
    assert layer.checkpoint_calls == [
        {
            "namespace": "amazon-products",
            "body": {"label": "catalog-2026-06-09"},
        }
    ]
    assert all(pipeline["stable"] for pipeline in body["pipelines"].values())


def test_index_checkpoint_refuses_active_ingest() -> None:
    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
    }
    extraction_pipeline_id = "hev-shop-extraction-jobs"
    layer = FakeLayerClient()
    layer.pipeline_statuses[extraction_pipeline_id] = PipelineStatus(
        pipeline_id=extraction_pipeline_id,
        counts={"pending": 1, "extracting": 1},
        pending_count=1,
        processing_count=1,
        failed_count=0,
        indexed_rate_per_min=0.0,
        rate_window_seconds=60,
    )
    app.state.settings = make_settings(extraction_pipeline_id=extraction_pipeline_id)
    app.state.layer = layer

    client = TestClient(app)
    try:
        response = client.post(
            "/index/checkpoint",
            json={"catalog_run_id": "catalog-2026-06-09"},
        )
    finally:
        for key, value in prev.items():
            setattr(app.state, key, value)

    assert response.status_code == 409
    assert layer.checkpoint_calls == []
    detail = response.json()["detail"]
    assert detail["pipelines"][extraction_pipeline_id]["pending_count"] == 1
    assert detail["pipelines"][extraction_pipeline_id]["processing_count"] == 1


def test_index_declares_minimal_amazon_products_schema() -> None:
    prev = {
        "settings": app.state.__dict__.get("settings"),
        "layer": app.state.__dict__.get("layer"),
    }
    layer = FakeLayerClient()
    app.state.settings = make_settings()
    app.state.layer = layer

    client = TestClient(app)
    try:
        response = client.post(
            "/index",
            json={"category": "Electronics", "count": 1, "job_size": 1},
        )
    finally:
        for key, value in prev.items():
            setattr(app.state, key, value)

    assert response.status_code == 200
    assert layer.schema_calls == [
        {
            "namespace": "amazon-products",
            "body": amazon_products_namespace_schema(),
            "with_perf": False,
        }
    ]
    schema = layer.schema_calls[0]["body"]
    assert schema["category"]["filterable"] is True
    assert schema["title"]["filterable"] is False
    assert schema["title"]["full_text_search"] is True
    assert schema["image_blob"] == {"type": "string", "filterable": False}
    assert "id" not in schema
    assert "_hevlayer_shard" not in schema
    assert "_hevlayer_upserted_at" not in schema
