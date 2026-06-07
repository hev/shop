from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from hevlayer import HevlayerError, PipelineStatus

from app import app
from tests._fakes import make_settings


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
