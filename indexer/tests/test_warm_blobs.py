"""Worker-level tests for the blob cache-warm reduce (`indexer/warm_blobs.py`)."""

from __future__ import annotations

import asyncio
import unittest

from hevlayer import WarmBlobsResponse

from warm_blobs import run_loop, warm_once

from _fakes import FakeLayerClient, make_settings


def _blobs(**overrides) -> WarmBlobsResponse:
    base = {
        "enabled": True,
        "status": "completed",
        "attributes": ["image_blob"],
        "budget_bytes": 1000,
        "documents_scanned": 10,
        "refs_seen": 8,
        "objects": 8,
        "bytes": 900,
        "missing": 0,
        "invalid_refs": 0,
        "budget_exhausted": False,
    }
    base.update(overrides)
    return WarmBlobsResponse(**base)


class WarmBlobsTests(unittest.IsolatedAsyncioTestCase):
    async def test_warm_once_requests_blobs_only_with_budget(self) -> None:
        layer = FakeLayerClient()
        settings = make_settings(
            blob_warm_budget_bytes=22_000_000_000, blob_warm_page_size=500
        )

        await warm_once(layer, settings)

        self.assertEqual(len(layer.hint_cache_warm_calls), 1)
        call = layer.hint_cache_warm_calls[0]
        self.assertEqual(call["namespace"], "amazon-products")
        self.assertTrue(call["blobs"])
        self.assertEqual(call["blob_budget_bytes"], 22_000_000_000)
        self.assertEqual(call["page_size"], 500)
        # Blobs-only: never touch the document/vector/snapshot warm steps.
        self.assertFalse(call["documents"])
        self.assertFalse(call["snapshots"])
        self.assertFalse(call["turbopuffer"])

    async def test_warm_once_returns_response(self) -> None:
        layer = FakeLayerClient()
        layer.warm_blobs_result = _blobs(objects=8, bytes=900)
        settings = make_settings()

        response = await warm_once(layer, settings)

        self.assertIsNotNone(response.blobs)
        self.assertEqual(response.blobs.objects, 8)

    async def test_warm_once_tolerates_budget_and_orphan_signals(self) -> None:
        # missing/invalid_refs and budget_exhausted should be handled (logged),
        # not raised — a warm that hits its budget or sees orphans still succeeds.
        layer = FakeLayerClient()
        layer.warm_blobs_result = _blobs(
            objects=40, bytes=1000, missing=3, invalid_refs=1, budget_exhausted=True
        )
        settings = make_settings()

        response = await warm_once(layer, settings)

        self.assertTrue(response.blobs.budget_exhausted)
        self.assertEqual(response.blobs.missing, 3)

    async def test_run_loop_warms_until_stopped(self) -> None:
        layer = FakeLayerClient()
        settings = make_settings(blob_warm_interval_seconds=0.01)
        stop = asyncio.Event()

        async def stopper() -> None:
            await asyncio.sleep(0.03)
            stop.set()

        await asyncio.gather(run_loop(layer, settings, stop), stopper())

        self.assertGreaterEqual(len(layer.hint_cache_warm_calls), 1)


if __name__ == "__main__":
    unittest.main()
