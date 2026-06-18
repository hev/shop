from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from embed import StageContext, _clip_image, _run_embed_products_once

from _fakes import FakeClipImageEmbedder, FakeLayerClient, make_settings


def make_ctx(
    layer: FakeLayerClient | None = None,
    settings=None,
    embedder: FakeClipImageEmbedder | None = None,
    image_status: int = 200,
) -> StageContext:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(image_status, content=b"image-bytes")

    return StageContext(
        settings=settings or make_settings(),
        layer=layer or FakeLayerClient(),
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        _clip_image=embedder,
    )


class EmbedProductsPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        http = getattr(getattr(self, "ctx", None), "http", None)
        if http is not None:
            await http.aclose()

    async def test_clip_warms_lazily_without_touching_pipelines(self) -> None:
        layer = FakeLayerClient()
        embedder = FakeClipImageEmbedder()
        self.ctx = make_ctx(layer=layer, embedder=None)

        with patch("hev_shop_common.embedders.CLIPImageEmbedder", return_value=embedder) as ctor:
            _clip_image(self.ctx)

        # Queue creation is app.py's job (the worker assumes it exists).
        self.assertEqual(layer.create_pipeline_calls, [])
        ctor.assert_called_once_with(self.ctx.settings)
        self.assertIs(self.ctx._clip_image, embedder)

    async def test_empty_claim_returns_zero(self) -> None:
        layer = FakeLayerClient()
        self.ctx = make_ctx(layer=layer, embedder=FakeClipImageEmbedder())

        result = await _run_embed_products_once(self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(layer.claim_calls[0]["pipeline_id"], "hev-shop-product-images")
        self.assertEqual(layer.claim_calls[0]["stage"], "pending")
        self.assertEqual(layer.claim_calls[0]["claim_stage"], "embedding")
        self.assertEqual(layer.pipeline_vector_calls, [])

    async def test_happy_path_writes_pipeline_vectors_without_manual_complete(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["A1"]
        layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "text": "Camera",
                    "metadata": {
                        "asin": "A1",
                        "title": "Camera",
                        "category": "Electronics",
                        "catalog_run_id": "catalog-2026-06-09",
                        "image_url": "https://example.test/a.jpg",
                    },
                }
            ]
        }
        embedder = FakeClipImageEmbedder()
        self.ctx = make_ctx(layer=layer, embedder=embedder)

        result = await _run_embed_products_once(self.ctx)

        self.assertEqual(result, 1)
        self.assertEqual(embedder.calls, [[b"image-bytes"]])
        self.assertEqual(
            layer.put_blob_calls,
            [{"namespace": "amazon-products", "body": b"image-bytes", "warm": None}],
        )
        self.assertEqual(len(layer.pipeline_vector_calls), 1)
        call = layer.pipeline_vector_calls[0]
        self.assertEqual(call["pipeline_id"], "hev-shop-product-images")
        self.assertEqual(call["document_id"], "A1")
        self.assertEqual(call["vectors"][0]["id"], "A1")
        self.assertEqual(call["vectors"][0]["attributes"]["asin"], "A1")
        self.assertNotIn("catalog_run_id", call["vectors"][0]["attributes"])
        self.assertEqual(
            call["vectors"][0]["attributes"]["image_url"],
            "https://example.test/a.jpg",
        )
        self.assertRegex(
            call["vectors"][0]["attributes"]["image_blob"],
            r"^blob://amazon-products/[0-9a-f]{64}$",
        )
        self.assertEqual(layer.complete_calls, [])
        self.assertEqual(layer.release_calls, [])

    async def test_missing_chunks_fails_document(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["A1"]
        self.ctx = make_ctx(layer=layer, embedder=FakeClipImageEmbedder())

        result = await _run_embed_products_once(self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(layer.fail_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(layer.fail_calls[0]["from_stage"], "embedding")

    async def test_chunk_fetch_failure_releases_document(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["A1"]
        layer.raise_on_get_chunks = True
        self.ctx = make_ctx(layer=layer, embedder=FakeClipImageEmbedder())

        result = await _run_embed_products_once(self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(layer.release_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(layer.release_calls[0]["from_stage"], "embedding")
        self.assertEqual(layer.fail_calls, [])

    async def test_missing_image_url_fails_document(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["A1"]
        layer.chunks_by_doc_id = {
            "A1": [{"id": "A1", "metadata": {"asin": "A1"}}],
        }
        self.ctx = make_ctx(layer=layer, embedder=FakeClipImageEmbedder())

        result = await _run_embed_products_once(self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(layer.fail_calls[0]["doc_ids"], ["A1"])

    async def test_image_download_failure_releases_document(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["A1"]
        layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "metadata": {
                        "asin": "A1",
                        "image_url": "https://example.test/missing.jpg",
                    },
                }
            ],
        }
        self.ctx = make_ctx(
            layer=layer, embedder=FakeClipImageEmbedder(), image_status=404
        )

        result = await _run_embed_products_once(self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(layer.release_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(layer.pipeline_vector_calls, [])

    async def test_embedder_failure_releases_document(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["A1"]
        layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "metadata": {
                        "asin": "A1",
                        "image_url": "https://example.test/a.jpg",
                    },
                }
            ],
        }
        embedder = FakeClipImageEmbedder()
        embedder.raise_on_call = True
        self.ctx = make_ctx(layer=layer, embedder=embedder)

        result = await _run_embed_products_once(self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(layer.release_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(layer.pipeline_vector_calls, [])

    async def test_blob_write_failure_releases_document(self) -> None:
        layer = FakeLayerClient()
        layer.next_claim = ["A1"]
        layer.raise_on_put_blob = True
        layer.chunks_by_doc_id = {
            "A1": [
                {
                    "id": "A1",
                    "metadata": {
                        "asin": "A1",
                        "image_url": "https://example.test/a.jpg",
                    },
                }
            ],
        }
        self.ctx = make_ctx(layer=layer, embedder=FakeClipImageEmbedder())

        result = await _run_embed_products_once(self.ctx)

        self.assertEqual(result, 0)
        self.assertEqual(layer.release_calls[0]["doc_ids"], ["A1"])
        self.assertEqual(layer.pipeline_vector_calls, [])


if __name__ == "__main__":
    unittest.main()
