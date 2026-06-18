from __future__ import annotations

import unittest
from types import SimpleNamespace

import httpx

import asyncio

from blob_backfill import (
    BackfillOptions,
    BackfillStats,
    count_document_state,
    dedupe_ids,
    process_ids,
    run_backfill,
)


def doc(doc_id: str, attrs: dict[str, object]):
    return SimpleNamespace(id=doc_id, attributes=attrs)


def options(apply: bool) -> BackfillOptions:
    return BackfillOptions(
        namespace="amazon-products",
        apply=apply,
        all=False,
        max_docs=100,
        ids=[],
        scan_id=None,
        start_offset=0,
        scan_page_size=100,
        fetch_batch_size=10,
        patch_batch_size=10,
        concurrency=2,
        image_timeout_seconds=5.0,
        warm=False,
        source="origin",
    )


class FakeLayer:
    def __init__(self, documents: list[object], missing: list[str] | None = None) -> None:
        self.documents = documents
        self.missing = missing or []
        self.put_blob_calls: list[dict[str, object]] = []
        self.patch_calls: list[dict[str, object]] = []
        self.scan_calls: list[dict[str, object]] = []
        self.wait_scan_calls: list[dict[str, object]] = []
        self.scan_results_calls: list[dict[str, object]] = []
        self.scan_ids = ["A1", "A2", "A3", "A4"]

    async def fetch_documents(self, namespace: str, body: dict[str, object]):
        ids = list(body.get("ids") or [])
        documents_by_id = {str(document.id): document for document in self.documents}
        documents = [documents_by_id[doc_id] for doc_id in ids if doc_id in documents_by_id]
        missing = self.missing or [
            doc_id for doc_id in ids if doc_id not in documents_by_id
        ]
        return SimpleNamespace(documents=documents, missing=missing)

    async def put_blob(self, namespace: str, body: bytes, warm: bool | None = None):
        self.put_blob_calls.append({"namespace": namespace, "body": body, "warm": warm})
        return SimpleNamespace(ref=f"blob://{namespace}/{len(self.put_blob_calls):064x}", size=len(body))

    async def patch_columns(
        self, namespace: str, ids: list[str], attrs: dict[str, list[object]]
    ):
        self.patch_calls.append({"namespace": namespace, "ids": ids, "attrs": attrs})
        return SimpleNamespace(rows_patched=len(ids))

    async def create_scan(self, namespace: str, body: dict[str, object]):
        self.scan_calls.append({"namespace": namespace, "body": body})
        return SimpleNamespace(id="scan-1")

    async def wait_for_scan(self, namespace: str, scan_id: str, timeout: object = None):
        self.wait_scan_calls.append(
            {"namespace": namespace, "scan_id": scan_id, "timeout": timeout}
        )
        return SimpleNamespace(id=scan_id, status="completed", error=None)

    async def get_scan_results(
        self, namespace: str, scan_id: str, limit: int, offset: int
    ):
        self.scan_results_calls.append(
            {
                "namespace": namespace,
                "scan_id": scan_id,
                "limit": limit,
                "offset": offset,
            }
        )
        return SimpleNamespace(
            ids=self.scan_ids[offset : offset + limit],
            total=len(self.scan_ids),
        )


class BlobBackfillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        http = getattr(self, "http", None)
        if http is not None:
            await http.aclose()

    def test_count_document_state_splits_candidates(self) -> None:
        candidates, already, missing = count_document_state(
            [
                doc("A1", {"image_url": "https://example.test/a.jpg"}),
                doc(
                    "A2",
                    {
                        "image_url": "https://example.test/b.jpg",
                        "image_blob": "blob://amazon-products/abc",
                    },
                ),
                doc("A3", {"title": "No image"}),
            ]
        )

        self.assertEqual([candidate.doc_id for candidate in candidates], ["A1"])
        self.assertEqual(already, 1)
        self.assertEqual(missing, 1)

    def test_dedupe_ids_trims_blanks_and_preserves_order(self) -> None:
        self.assertEqual(dedupe_ids([" A1 ", "", "A2", "A1"]), ["A1", "A2"])

    async def test_process_ids_dry_run_counts_without_writes(self) -> None:
        layer = FakeLayer(
            [
                doc("A1", {"image_url": "https://example.test/a.jpg"}),
                doc(
                    "A2",
                    {
                        "image_url": "https://example.test/b.jpg",
                        "image_blob": "blob://amazon-products/abc",
                    },
                ),
                doc("A3", {}),
            ],
            missing=["A4"],
        )
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        stats = BackfillStats()

        await process_ids(layer, self.http, options(False), ["A1", "A2", "A3", "A4"], stats)

        self.assertEqual(stats.fetched, 3)
        self.assertEqual(stats.already_backfilled, 1)
        self.assertEqual(stats.missing_image_url, 2)
        self.assertEqual(stats.attempted, 1)
        self.assertEqual(stats.patched, 0)
        self.assertEqual(layer.put_blob_calls, [])
        self.assertEqual(layer.patch_calls, [])

    async def test_process_ids_apply_puts_blobs_and_patches_successes(self) -> None:
        layer = FakeLayer(
            [
                doc("A1", {"image_url": "https://example.test/a.jpg"}),
                doc("A2", {"image_url": "https://example.test/missing.jpg"}),
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("missing.jpg"):
                return httpx.Response(404)
            return httpx.Response(200, content=b"image-bytes")

        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        stats = BackfillStats()

        await process_ids(layer, self.http, options(True), ["A1", "A2"], stats)

        self.assertEqual(stats.attempted, 2)
        self.assertEqual(stats.failed, 1)
        self.assertEqual(stats.patched, 1)
        self.assertEqual(stats.bytes_stored, len(b"image-bytes"))
        self.assertEqual(
            layer.put_blob_calls,
            [{"namespace": "amazon-products", "body": b"image-bytes", "warm": None}],
        )
        self.assertEqual(layer.patch_calls[0]["ids"], ["A1"])
        self.assertEqual(
            layer.patch_calls[0]["attrs"]["image_blob"][0],
            "blob://amazon-products/0000000000000000000000000000000000000000000000000000000000000001",
        )

    async def test_run_backfill_with_explicit_ids_skips_scan(self) -> None:
        layer = FakeLayer([doc("A1", {"image_url": "https://example.test/a.jpg"})])
        self.http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        )
        explicit = options(False)
        explicit = BackfillOptions(**{**explicit.__dict__, "ids": ["A1"]})

        stats = await run_backfill(layer, self.http, explicit, asyncio.Event())

        self.assertEqual(stats.inspected, 1)
        self.assertEqual(stats.attempted, 1)
        self.assertEqual(stats.scan_id, None)
        self.assertEqual(layer.scan_calls, [])

    async def test_run_backfill_reuses_scan_id_and_offsets_results(self) -> None:
        layer = FakeLayer(
            [
                doc("A1", {"image_url": "https://example.test/a.jpg"}),
                doc("A2", {"image_url": "https://example.test/b.jpg"}),
                doc("A3", {"image_url": "https://example.test/c.jpg"}),
                doc("A4", {"image_url": "https://example.test/d.jpg"}),
            ]
        )
        self.http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        )
        resumed = options(False)
        resumed = BackfillOptions(
            **{
                **resumed.__dict__,
                "scan_id": "scan-existing",
                "start_offset": 2,
                "max_docs": 1,
            }
        )

        stats = await run_backfill(layer, self.http, resumed, asyncio.Event())

        self.assertEqual(stats.scan_id, "scan-existing")
        self.assertEqual(stats.start_offset, 2)
        self.assertEqual(stats.next_offset, 3)
        self.assertEqual(stats.total, 4)
        self.assertEqual(stats.inspected, 1)
        self.assertEqual(stats.attempted, 1)
        self.assertEqual(layer.scan_calls, [])
        self.assertEqual(layer.wait_scan_calls, [])
        self.assertEqual(
            layer.scan_results_calls,
            [
                {
                    "namespace": "amazon-products",
                    "scan_id": "scan-existing",
                    "limit": 1,
                    "offset": 2,
                }
            ],
        )
