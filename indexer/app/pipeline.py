"""Product embedding worker for the Layer pipeline document lifecycle.

CPU extraction workers stage product chunks into `pending`. GPU workers claim
those documents into `embedding`, fetch image bytes in memory, and call
`put_pipeline_document_vectors`, which writes vectors and marks the document
`indexed`.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from hevlayer import (
    AsyncHevlayer,
    ClaimDocumentsRequest,
    CreatePipelineRequest,
    HeartbeatDocumentsRequest,
    PutVectorsRequest,
    VectorEntry,
)

from hev_shop_common.config import Settings, get_settings
from hev_shop_common.records import product_vector_attributes

logger = logging.getLogger(__name__)


@dataclass
class StageContext:
    settings: Settings
    layer: AsyncHevlayer
    http: httpx.AsyncClient | None = None
    _clip_image: Any = None


@asynccontextmanager
async def _http_client(ctx: StageContext) -> AsyncIterator[httpx.AsyncClient]:
    if ctx.http is not None:
        yield ctx.http
        return
    client = httpx.AsyncClient(
        timeout=ctx.settings.http_timeout_seconds,
        follow_redirects=True,
    )
    try:
        ctx.http = client
        yield client
    finally:
        ctx.http = None
        await client.aclose()


async def setup_embed_products(ctx: StageContext) -> None:
    await ctx.layer.ensure_pipeline(
        CreatePipelineRequest(
            id=ctx.settings.default_pipeline_id,
            target_namespace=ctx.settings.namespace,
            distance_metric=ctx.settings.distance_metric,
        )
    )
    _clip_image(ctx)


async def run_embed_products(ctx: StageContext, stop: asyncio.Event) -> None:
    await setup_embed_products(ctx)
    async with _http_client(ctx):
        while not stop.is_set():
            n = await _run_embed_products_once(ctx)
            if n == 0:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), ctx.settings.worker_poll_seconds)


async def _run_embed_products_once(ctx: StageContext) -> int:
    pipeline_id = ctx.settings.default_pipeline_id
    worker_id = ctx.settings.resolved_worker_id
    claim = await ctx.layer.claim_documents(
        pipeline_id,
        ClaimDocumentsRequest(
            stage="pending",
            claim_stage="embedding",
            limit=ctx.settings.embedding_claim_size,
            worker_id=worker_id,
            lease_seconds=ctx.settings.claim_lease_seconds,
        ),
    )
    doc_ids = list(claim.documents)
    if not doc_ids:
        return 0

    active = set(doc_ids)
    heartbeat = asyncio.create_task(_heartbeat(ctx, active))
    try:
        return await _embed_claimed_products(ctx, doc_ids)
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


async def _embed_claimed_products(ctx: StageContext, doc_ids: list[str]) -> int:
    fail: list[str] = []
    release: list[str] = []
    prepared: list[tuple[str, str, dict[str, Any]]] = []

    for doc_id in doc_ids:
        try:
            chunks = await ctx.layer.get_pipeline_document_chunks(
                ctx.settings.default_pipeline_id, doc_id
            )
        except Exception:
            logger.exception("failed to fetch product chunks", extra={"doc_id": doc_id})
            release.append(doc_id)
            continue
        if not chunks:
            fail.append(doc_id)
            continue
        metadata = chunks[0].metadata or {}
        image_url = str(metadata.get("image_url") or "").strip()
        if not image_url:
            fail.append(doc_id)
            continue
        prepared.append((doc_id, image_url, product_vector_attributes(metadata, doc_id)))

    if fail:
        await ctx.layer.fail_documents(
            ctx.settings.default_pipeline_id,
            fail,
            from_stage="embedding",
            worker_id=ctx.settings.resolved_worker_id,
        )
    complete = 0
    if prepared:
        async with _http_client(ctx) as http:
            for batch in _batches(prepared, ctx.settings.embedding_batch_size):
                try:
                    images = await asyncio.gather(
                        *(
                            _fetch_image_bytes(http, image_url)
                            for _doc_id, image_url, _attrs in batch
                        )
                    )
                    vectors = await asyncio.to_thread(
                        _clip_image(ctx).encode_image_bytes, images
                    )
                except Exception:
                    logger.exception("CLIP product image batch failed")
                    release.extend(doc_id for doc_id, _image_url, _attrs in batch)
                    continue

                for (doc_id, _image_url, attrs), vector in zip(
                    batch, vectors, strict=True
                ):
                    try:
                        await ctx.layer.put_pipeline_document_vectors(
                            ctx.settings.default_pipeline_id,
                            doc_id,
                            PutVectorsRequest(
                                vectors=[
                                    VectorEntry(
                                        id=doc_id,
                                        vector=vector,
                                        attributes=attrs,
                                    )
                                ]
                            ),
                        )
                        complete += 1
                    except Exception:
                        logger.exception(
                            "failed to write product vector", extra={"doc_id": doc_id}
                        )
                        release.append(doc_id)

    if release:
        await ctx.layer.release_documents(
            ctx.settings.default_pipeline_id,
            sorted(set(release)),
            from_stage="embedding",
            worker_id=ctx.settings.resolved_worker_id,
        )
    return complete


async def _fetch_image_bytes(http: httpx.AsyncClient, image_url: str) -> bytes:
    response = await http.get(image_url)
    response.raise_for_status()
    return response.content


async def _heartbeat(ctx: StageContext, active: set[str]) -> None:
    while True:
        await asyncio.sleep(ctx.settings.claim_heartbeat_seconds)
        if active:
            await ctx.layer.heartbeat_documents(
                ctx.settings.default_pipeline_id,
                HeartbeatDocumentsRequest(
                    document_ids=sorted(active),
                    stage="embedding",
                    worker_id=ctx.settings.resolved_worker_id,
                ),
            )


def _clip_image(ctx: StageContext):
    if ctx._clip_image is None:
        from hev_shop_common.embedders import CLIPImageEmbedder

        ctx._clip_image = CLIPImageEmbedder(ctx.settings)
    return ctx._clip_image


def _batches[T](items: list[T], size: int) -> list[list[T]]:
    size = max(1, size)
    return [items[i : i + size] for i in range(0, len(items), size)]


async def amain() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    layer = AsyncHevlayer(
        api_key=settings.layer_api_key,
        base_url=settings.layer_gateway_url,
        timeout=settings.http_timeout_seconds,
    )
    ctx = StageContext(settings=settings, layer=layer)
    stop = asyncio.Event()
    _install_signals(stop)
    try:
        await run_embed_products(ctx, stop)
    finally:
        await layer.aclose()


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


if __name__ == "__main__":
    asyncio.run(amain())
