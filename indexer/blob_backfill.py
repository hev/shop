"""Backfill Layer-owned image blobs for existing product rows.

The embed worker writes `image_blob` for new products. This helper covers rows
that already existed before that path shipped: scan IDs, fetch `image_url` and
`image_blob`, PUT missing blobs, then PATCH the string reference back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import httpx
from hevlayer import AsyncHevlayer, HevlayerError

from hev_shop_common.config import Settings, get_settings

logger = logging.getLogger(__name__)

IMAGE_ATTRIBUTES = ["image_url", "image_blob"]


@dataclass
class BackfillStats:
    scan_id: str | None = None
    start_offset: int = 0
    next_offset: int = 0
    total: int | None = None
    inspected: int = 0
    fetched: int = 0
    already_backfilled: int = 0
    missing_image_url: int = 0
    attempted: int = 0
    patched: int = 0
    failed: int = 0
    bytes_stored: int = 0


@dataclass(frozen=True)
class BackfillCandidate:
    doc_id: str
    image_url: str


@dataclass(frozen=True)
class BackfillOptions:
    namespace: str
    apply: bool
    all: bool
    max_docs: int
    ids: list[str]
    scan_id: str | None
    start_offset: int
    scan_page_size: int
    fetch_batch_size: int
    patch_batch_size: int
    concurrency: int
    image_timeout_seconds: float
    warm: bool
    source: str

    @property
    def doc_limit(self) -> int | None:
        if self.all:
            return None
        return max(0, self.max_docs)


def needs_blob(document: Any) -> BackfillCandidate | None:
    attrs = getattr(document, "attributes", None) or {}
    image_blob = str(attrs.get("image_blob") or "").strip()
    if image_blob.startswith("blob://"):
        return None
    image_url = str(attrs.get("image_url") or "").strip()
    if not image_url:
        return None
    return BackfillCandidate(doc_id=str(document.id), image_url=image_url)


def count_document_state(documents: Iterable[Any]) -> tuple[list[BackfillCandidate], int, int]:
    candidates: list[BackfillCandidate] = []
    already_backfilled = 0
    missing_image_url = 0
    for document in documents:
        attrs = getattr(document, "attributes", None) or {}
        image_blob = str(attrs.get("image_blob") or "").strip()
        if image_blob.startswith("blob://"):
            already_backfilled += 1
            continue
        candidate = needs_blob(document)
        if candidate is None:
            missing_image_url += 1
            continue
        candidates.append(candidate)
    return candidates, already_backfilled, missing_image_url


async def run_backfill(
    layer: AsyncHevlayer,
    http: httpx.AsyncClient,
    options: BackfillOptions,
    stop: asyncio.Event,
) -> BackfillStats:
    stats = BackfillStats()
    if options.ids:
        for start in range(0, len(options.ids), options.fetch_batch_size):
            ids = options.ids[start : start + options.fetch_batch_size]
            stats.inspected += len(ids)
            await process_ids(layer, http, options, ids, stats)
        return stats

    stats.start_offset = max(0, options.start_offset)
    stats.next_offset = stats.start_offset
    if options.scan_id:
        stats.scan_id = options.scan_id
    else:
        scan = await layer.create_scan(
            options.namespace,
            {
                "mode": "ids",
                "source": options.source,
                "page_size": options.scan_page_size,
                "timeout_seconds": 120,
            },
        )
        stats.scan_id = scan.id
        scan = await layer.wait_for_scan(options.namespace, scan.id, timeout=None)
        if scan.status == "failed":
            raise RuntimeError(f"scan {scan.id} failed: {scan.error}")

    offset = stats.start_offset
    remaining = options.doc_limit
    while not stop.is_set():
        limit = options.fetch_batch_size
        if remaining is not None:
            if remaining <= 0:
                break
            limit = min(limit, remaining)
        page = await layer.get_scan_results(
            options.namespace,
            stats.scan_id,
            limit=limit,
            offset=offset,
        )
        ids = list(getattr(page, "ids", []) or [])
        stats.total = int(getattr(page, "total", offset + len(ids)))
        if not ids:
            break
        offset += len(ids)
        stats.next_offset = offset
        if remaining is not None:
            remaining -= len(ids)
        stats.inspected += len(ids)
        await process_ids(layer, http, options, ids, stats)
        if offset >= stats.total:
            break
    return stats


async def process_ids(
    layer: AsyncHevlayer,
    http: httpx.AsyncClient,
    options: BackfillOptions,
    ids: list[str],
    stats: BackfillStats,
) -> None:
    response = await layer.fetch_documents(
        options.namespace,
        {"ids": ids, "include_attributes": IMAGE_ATTRIBUTES},
    )
    documents = list(response.documents)
    stats.fetched += len(documents)
    candidates, already_backfilled, missing_image_url = count_document_state(documents)
    stats.already_backfilled += already_backfilled
    stats.missing_image_url += missing_image_url + len(response.missing)
    if not candidates:
        return
    stats.attempted += len(candidates)
    if not options.apply:
        return

    semaphore = asyncio.Semaphore(max(1, options.concurrency))
    tasks = [
        asyncio.create_task(backfill_one(layer, http, options, candidate, semaphore))
        for candidate in candidates
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    patched_ids: list[str] = []
    refs: list[str] = []
    for candidate, result in zip(candidates, results, strict=True):
        if isinstance(result, Exception):
            logger.warning(
                "image blob backfill failed",
                extra={"doc_id": candidate.doc_id, "image_url": candidate.image_url},
                exc_info=(type(result), result, result.__traceback__),
            )
            stats.failed += 1
            continue
        ref, size = result
        patched_ids.append(candidate.doc_id)
        refs.append(ref)
        stats.bytes_stored += size

    for start in range(0, len(patched_ids), max(1, options.patch_batch_size)):
        batch_ids = patched_ids[start : start + options.patch_batch_size]
        batch_refs = refs[start : start + options.patch_batch_size]
        try:
            await layer.patch_columns(
                options.namespace,
                batch_ids,
                {"image_blob": batch_refs},
            )
        except Exception:
            logger.exception("failed to patch image_blob batch")
            stats.failed += len(batch_ids)
        else:
            stats.patched += len(batch_ids)


async def backfill_one(
    layer: AsyncHevlayer,
    http: httpx.AsyncClient,
    options: BackfillOptions,
    candidate: BackfillCandidate,
    semaphore: asyncio.Semaphore,
) -> tuple[str, int]:
    async with semaphore:
        image = await fetch_image(http, candidate.image_url)
        blob = await layer.put_blob(
            options.namespace,
            image,
            warm=True if options.warm else None,
        )
        return blob.ref, int(blob.size)


async def fetch_image(http: httpx.AsyncClient, image_url: str) -> bytes:
    response = await http.get(image_url)
    response.raise_for_status()
    if not response.content:
        raise ValueError("image response was empty")
    return response.content


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write blobs and patch image_blob. Without this, only reports candidates.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Inspect every scan result. By default only --max-docs are inspected.",
    )
    parser.add_argument("--max-docs", type=int, default=1000)
    parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        default=[],
        help="Specific product ID/ASIN to inspect. Can be repeated; skips scan creation.",
    )
    parser.add_argument(
        "--ids-file",
        default=None,
        help="Newline-delimited product IDs/ASINs to inspect; skips scan creation.",
    )
    parser.add_argument(
        "--scan-id",
        default=None,
        help="Reuse a completed Layer ids scan instead of creating a new one.",
    )
    parser.add_argument(
        "--start-offset",
        type=int,
        default=0,
        help="Offset into scan results to start from; useful with --scan-id and --max-docs.",
    )
    parser.add_argument("--scan-page-size", type=int, default=1000)
    parser.add_argument("--fetch-batch-size", type=int, default=100)
    parser.add_argument("--patch-batch-size", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--image-timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--warm",
        action="store_true",
        help="Pass warm=true on blob PUTs. Default is durable write only.",
    )
    parser.add_argument(
        "--source",
        choices=["origin", "cache", "auto"],
        default="origin",
        help="Layer scan source for collecting product IDs.",
    )
    parser.add_argument("--json", action="store_true", help="Print only JSON stats.")
    return parser.parse_args()


async def amain() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.WARNING if args.json else logging.INFO)
    settings = get_settings()
    ids = list(args.ids or [])
    if args.ids_file:
        with open(args.ids_file) as handle:
            ids.extend(line.strip() for line in handle if line.strip())
    options = BackfillOptions(
        namespace=args.namespace or settings.namespace,
        apply=args.apply,
        all=args.all,
        max_docs=args.max_docs,
        ids=dedupe_ids(ids),
        scan_id=args.scan_id,
        start_offset=args.start_offset,
        scan_page_size=args.scan_page_size,
        fetch_batch_size=args.fetch_batch_size,
        patch_batch_size=args.patch_batch_size,
        concurrency=args.concurrency,
        image_timeout_seconds=args.image_timeout_seconds,
        warm=args.warm,
        source=args.source,
    )
    if options.apply and options.all:
        logger.warning("running full image blob backfill with writes enabled")
    timeout = httpx.Timeout(options.image_timeout_seconds)
    layer = AsyncHevlayer(
        api_key=settings.layer_api_key,
        base_url=settings.layer_gateway_url,
        timeout=settings.http_timeout_seconds,
    )
    stop = asyncio.Event()
    install_signals(stop)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http:
            stats = await run_backfill(layer, http, options, stop)
    except HevlayerError as exc:
        raise SystemExit(f"Layer request failed: {exc.status_code} {exc.message}") from exc
    finally:
        await layer.aclose()

    payload = {
        "namespace": options.namespace,
        "apply": options.apply,
        "all": options.all,
        "ids": options.ids,
        **asdict(stats),
    }
    print(json.dumps(payload, indent=None if args.json else 2, sort_keys=True))


def install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


def dedupe_ids(ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for doc_id in ids:
        normalized = doc_id.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


if __name__ == "__main__":
    if not os.environ.get("PYTHONUNBUFFERED"):
        os.environ["PYTHONUNBUFFERED"] = "1"
    asyncio.run(amain())
