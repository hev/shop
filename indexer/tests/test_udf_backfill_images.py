"""Tests for the backfill-images UDF.

The UDF is just a function — the gateway (or the SDK's `run_udf_worker`)
calls it per row. We assert the per-row behavior: success returns a Blob;
transient errors retry; permanent errors dead-letter.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import httpx
import pytest

from hevlayer.udf import Blob, PermanentError, TransientError


@pytest.fixture
def backfill_images_module(monkeypatch):
    """Import the UDF module fresh so each test can inject its own httpx client."""
    if "app.udfs.backfill_images" in sys.modules:
        del sys.modules["app.udfs.backfill_images"]
    monkeypatch.setenv("BLOB_MAX_BYTES", str(512 * 1024))
    module = importlib.import_module("app.udfs.backfill_images")
    return module


def install_client(module, *, response=None, exc=None) -> MagicMock:
    """Replace the module-level httpx client with a mock that returns `response`
    or raises `exc`."""
    client = MagicMock()
    if exc is not None:
        client.get.side_effect = exc
    else:
        client.get.return_value = response
    module._client = client
    return client


def make_response(*, status: int = 200, content: bytes = b"\xff\xd8\xff\xd9", content_type: str = "image/jpeg") -> httpx.Response:
    request = httpx.Request("GET", "https://m.media-amazon.com/images/I/test.jpg")
    return httpx.Response(
        status_code=status,
        headers={"content-type": content_type},
        content=content,
        request=request,
    )


def test_fetch_image_success_returns_blob(backfill_images_module) -> None:
    install_client(backfill_images_module, response=make_response())

    blob = backfill_images_module.fetch_image(
        id="B00FI7TCGI",
        image_url="https://m.media-amazon.com/images/I/test.jpg",
    )

    assert isinstance(blob, Blob)
    assert blob.content_type == "image/jpeg"
    assert blob.data == b"\xff\xd8\xff\xd9"


def test_fetch_image_strips_content_type_charset(backfill_images_module) -> None:
    install_client(
        backfill_images_module,
        response=make_response(content_type="image/png; charset=binary"),
    )

    blob = backfill_images_module.fetch_image(
        id="B00FI7TCGI",
        image_url="https://example.test/i.png",
    )

    assert blob.content_type == "image/png"


def test_fetch_image_empty_url_is_permanent(backfill_images_module) -> None:
    install_client(backfill_images_module, response=make_response())

    with pytest.raises(PermanentError):
        backfill_images_module.fetch_image(id="B00FI7TCGI", image_url="")


def test_fetch_image_404_is_permanent(backfill_images_module) -> None:
    install_client(
        backfill_images_module,
        response=make_response(status=404, content=b"", content_type="text/html"),
    )

    with pytest.raises(PermanentError):
        backfill_images_module.fetch_image(
            id="B00FI7TCGI",
            image_url="https://m.media-amazon.com/images/I/gone.jpg",
        )


def test_fetch_image_429_is_transient(backfill_images_module) -> None:
    install_client(
        backfill_images_module,
        response=make_response(status=429, content=b"", content_type="text/plain"),
    )

    with pytest.raises(TransientError):
        backfill_images_module.fetch_image(
            id="B00FI7TCGI",
            image_url="https://m.media-amazon.com/images/I/test.jpg",
        )


def test_fetch_image_503_is_transient(backfill_images_module) -> None:
    install_client(
        backfill_images_module,
        response=make_response(status=503, content=b"", content_type="text/html"),
    )

    with pytest.raises(TransientError):
        backfill_images_module.fetch_image(
            id="B00FI7TCGI",
            image_url="https://m.media-amazon.com/images/I/test.jpg",
        )


def test_fetch_image_timeout_is_transient(backfill_images_module) -> None:
    install_client(
        backfill_images_module,
        exc=httpx.ConnectTimeout("timeout"),
    )

    with pytest.raises(TransientError):
        backfill_images_module.fetch_image(
            id="B00FI7TCGI",
            image_url="https://m.media-amazon.com/images/I/test.jpg",
        )


def test_fetch_image_non_image_content_type_is_permanent(backfill_images_module) -> None:
    install_client(
        backfill_images_module,
        response=make_response(content=b"<html>", content_type="text/html"),
    )

    with pytest.raises(PermanentError):
        backfill_images_module.fetch_image(
            id="B00FI7TCGI",
            image_url="https://m.media-amazon.com/images/I/test.jpg",
        )


def test_fetch_image_oversize_is_permanent(backfill_images_module, monkeypatch) -> None:
    monkeypatch.setattr(backfill_images_module, "BLOB_MAX_BYTES", 64)
    install_client(
        backfill_images_module,
        response=make_response(content=b"X" * 256, content_type="image/jpeg"),
    )

    with pytest.raises(PermanentError):
        backfill_images_module.fetch_image(
            id="B00FI7TCGI",
            image_url="https://m.media-amazon.com/images/I/big.jpg",
        )


def test_udf_decorator_metadata_present(backfill_images_module) -> None:
    metadata = getattr(backfill_images_module.fetch_image, "__hevlayer_udf__", None)

    assert metadata is not None
    assert metadata["inputs"] == ["id", "image_url"]
    assert metadata["output"] == "image"
    assert metadata["kind"] == "blob"
