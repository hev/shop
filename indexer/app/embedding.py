from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import Settings
from .database import Database
from .layer_client import LayerClient
from .reviews import REVIEW_EMBED_PREFIX, review_namespace_for
from .vector_attrs import product_vector_attributes, review_vector_attributes

logger = logging.getLogger(__name__)


def batches[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


async def run_worker_loop(
    process_once: Callable[[], Awaitable[int]],
    *,
    poll_seconds: float,
    stop_event: asyncio.Event | None = None,
) -> None:
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        task = asyncio.create_task(process_once())
        stop_task = asyncio.create_task(stop_event.wait())
        done, _pending = await asyncio.wait(
            {task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if stop_task in done and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            break

        stop_task.cancel()
        with suppress(asyncio.CancelledError):
            await stop_task

        processed = task.result()
        if processed == 0:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)


class CLIPImageEmbedder:
    def __init__(self, settings: Settings) -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self._torch = torch
        if settings.clip_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.clip_device

        self.processor = CLIPProcessor.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model = CLIPModel.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model.to(self.device)
        self.model.eval()

    def encode_image_paths(self, paths: list[Path]) -> list[list[float]]:
        from PIL import Image

        images = []
        for path in paths:
            with Image.open(path) as image:
                images.append(image.convert("RGB").copy())

        inputs = self.processor(images=images, return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            features = self.model.get_image_features(**inputs)
            if not isinstance(features, self._torch.Tensor):
                features = features.pooler_output
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features.cpu().float().tolist()


class CLIPTextEmbedder:
    def __init__(self, settings: Settings) -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self._torch = torch
        if settings.clip_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.clip_device

        self.processor = CLIPProcessor.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model = CLIPModel.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model.to(self.device)
        self.model.eval()

    def encode_text(self, text: str) -> list[float]:
        inputs = self.processor(
            text=[text], return_tensors="pt", padding=True, truncation=True
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            features = self.model.get_text_features(**inputs)
            if not isinstance(features, self._torch.Tensor):
                features = features.pooler_output
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features[0].cpu().float().tolist()


class QwenTextEmbedder:
    def __init__(self, settings: Settings) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        if settings.review_embedding_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.review_embedding_device

        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.review_embedding_model_name,
            cache_dir=str(settings.model_cache_dir),
        )
        model_kwargs: dict[str, Any] = {}
        if str(self.device).startswith("cuda"):
            model_kwargs["torch_dtype"] = torch.float16
            model_kwargs["low_cpu_mem_usage"] = True
            model_kwargs["device_map"] = {"": self.device}
        self.model = AutoModel.from_pretrained(
            settings.review_embedding_model_name,
            cache_dir=str(settings.model_cache_dir),
            **model_kwargs,
        )
        if "device_map" not in model_kwargs:
            self.model.to(self.device)
        self.model.eval()

    def chunk_text(
        self, text: str, *, chunk_tokens: int, chunk_overlap: int
    ) -> list[str]:
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_tokens:
            raise ValueError("chunk_overlap must be non-negative and less than chunk_tokens")
        token_ids = self.tokenizer.encode(text, add_special_tokens=False)
        if not token_ids:
            return []
        chunks: list[str] = []
        step = chunk_tokens - chunk_overlap
        for start in range(0, len(token_ids), step):
            window = token_ids[start : start + chunk_tokens]
            if not window:
                continue
            chunk = self.tokenizer.decode(window, skip_special_tokens=True).strip()
            if chunk:
                chunks.append(chunk)
            if start + chunk_tokens >= len(token_ids):
                break
        return chunks

    def encode_texts(self, texts: list[str]) -> list[list[float]]:
        inputs = self.tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=8192,
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            outputs = self.model(**inputs)
            hidden = outputs.last_hidden_state
            mask = inputs["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
            summed = (hidden * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1e-9)
            features = summed / counts
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features.cpu().float().tolist()


class EmbeddingWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        layer: LayerClient,
        embedder: CLIPImageEmbedder,
        pipeline_id: str,
        namespace_resolver: Callable[[dict[str, Any], str], str],
        document_id_prefix: str | None = None,
        include_review_tag_attrs: bool = False,
    ) -> None:
        self.settings = settings
        self.database = database
        self.layer = layer
        self.embedder = embedder
        self.pipeline_id = pipeline_id
        self.namespace_resolver = namespace_resolver
        self.document_id_prefix = document_id_prefix
        self.include_review_tag_attrs = include_review_tag_attrs

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        await run_worker_loop(
            self.process_once,
            poll_seconds=self.settings.worker_poll_seconds,
            stop_event=stop_event,
        )

    async def claim_documents(self) -> list[str]:
        return await self.layer.claim_pipeline_documents(
            self.pipeline_id,
            limit=self.settings.embedding_claim_size,
            worker_id=self.settings.resolved_worker_id,
            lease_seconds=self.settings.claim_lease_seconds,
            claim_stage="embedding",
            document_id_prefix=self.document_id_prefix,
        )

    async def release_documents(self, document_ids: list[str]) -> None:
        await self.layer.release_pipeline_documents(
            self.pipeline_id,
            document_ids,
            from_stage="embedding",
            worker_id=self.settings.resolved_worker_id,
        )

    async def release_document(self, document_id: str) -> None:
        await self.release_documents([document_id])

    async def fail_documents(self, document_ids: list[str]) -> None:
        await self.layer.fail_pipeline_documents(
            self.pipeline_id,
            document_ids,
            from_stage="embedding",
            worker_id=self.settings.resolved_worker_id,
        )

    async def fail_document(self, document_id: str) -> None:
        await self.fail_documents([document_id])

    async def complete_documents(self, document_ids: list[str]) -> None:
        await self.layer.complete_pipeline_documents(
            self.pipeline_id,
            document_ids,
            from_stage="embedding",
            worker_id=self.settings.resolved_worker_id,
        )

    async def process_once(self) -> int:
        doc_ids = await self.claim_documents()
        if not doc_ids:
            return 0
        active_doc_ids = set(doc_ids)
        heartbeat = asyncio.create_task(self.heartbeat_documents(active_doc_ids))
        semaphore = asyncio.Semaphore(self.settings.chunk_fetch_concurrency)

        async def prepare(
            doc_id: str,
        ) -> tuple[str, str, str, Path, dict[str, Any]] | None:
            try:
                async with semaphore:
                    chunks = await self.layer.get_chunks(
                        self.pipeline_id, doc_id
                    )
                if not chunks:
                    await self.fail_document(doc_id)
                    active_doc_ids.discard(doc_id)
                    return None
                chunk = chunks[0]
                metadata = chunk.get("metadata") or {}
                image_path = Path(metadata.get("image_path", ""))
                if not image_path.is_file():
                    await self.fail_document(doc_id)
                    active_doc_ids.discard(doc_id)
                    return None
                attrs = product_vector_attributes(metadata, doc_id)
                if self.include_review_tag_attrs:
                    attrs.update(
                        await self.database.aggregate_review_tag_attrs(
                            str(attrs["asin"]),
                            min_count=self.settings.review_tag_min_count,
                            min_fraction=self.settings.review_tag_min_fraction,
                            sample_count=self.settings.review_tag_sample_count,
                        )
                    )
                namespace = self.namespace_resolver(metadata, doc_id)
                return (namespace, doc_id, chunk["id"], image_path, attrs)
            except Exception:
                logger.exception("failed to prepare document", extra={"doc_id": doc_id})
                await self.release_document(doc_id)
                active_doc_ids.discard(doc_id)
                return None

        logger.info("claimed %s pending documents for embedding", len(doc_ids))
        try:
            prepared = await asyncio.gather(*(prepare(doc_id) for doc_id in doc_ids))
            items = [item for item in prepared if item is not None]
            if not items:
                return 0

            upserts: list[dict[str, Any]] = []
            upsert_doc_ids: list[tuple[str, str, Path]] = []
            written = 0
            for embedding_items in batches(items, self.settings.embedding_batch_size):
                try:
                    vectors = self.embedder.encode_image_paths(
                        [item[3] for item in embedding_items]
                    )
                except Exception:
                    logger.exception("CLIP batch embedding failed")
                    batch_doc_ids = [item[1] for item in embedding_items]
                    await self.release_documents(batch_doc_ids)
                    active_doc_ids.difference_update(batch_doc_ids)
                    continue

                for (namespace, doc_id, vector_id, image_path, attrs), vector in zip(
                    embedding_items, vectors, strict=True
                ):
                    upserts.append({"id": vector_id, "vector": vector, "attributes": attrs})
                    upsert_doc_ids.append((namespace, doc_id, image_path))

            if not upserts:
                return 0

            by_namespace: dict[str, list[tuple[str, dict[str, Any], Path]]] = {}
            for (namespace, doc_id, image_path), upsert in zip(
                upsert_doc_ids, upserts, strict=True
            ):
                by_namespace.setdefault(namespace, []).append((doc_id, upsert, image_path))

            for namespace, namespace_items in by_namespace.items():
                for upsert_items in batches(
                    namespace_items,
                    self.settings.vector_upsert_batch_size,
                ):
                    batch_doc_ids = [item[0] for item in upsert_items]
                    batch_upserts = [item[1] for item in upsert_items]
                    batch_image_paths = [item[2] for item in upsert_items]
                    try:
                        await self.layer.upsert_vectors(namespace, batch_upserts)
                        await self.complete_documents(batch_doc_ids)
                        await self.cleanup_image_paths(batch_image_paths)
                        active_doc_ids.difference_update(batch_doc_ids)
                        written += len(batch_upserts)
                        logger.info(
                            "upserted %s vectors to namespace %s",
                            len(batch_upserts),
                            namespace,
                        )
                    except Exception:
                        logger.exception("failed to upsert vector batch")
                        await self.release_documents(batch_doc_ids)
                        active_doc_ids.difference_update(batch_doc_ids)

            return written
        except asyncio.CancelledError:
            if active_doc_ids:
                await self.release_documents(sorted(active_doc_ids))
                active_doc_ids.clear()
            raise
        except Exception:
            if active_doc_ids:
                await self.release_documents(sorted(active_doc_ids))
                active_doc_ids.clear()
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def cleanup_image_paths(self, paths: list[Path]) -> None:
        if not self.settings.cleanup_embedded_images:
            return

        for path in set(paths):
            try:
                await asyncio.to_thread(path.unlink)
            except FileNotFoundError:
                pass
            except Exception:
                logger.warning(
                    "failed to remove embedded image",
                    extra={"image_path": str(path)},
                    exc_info=True,
                )

    async def heartbeat_documents(self, active_doc_ids: set[str]) -> None:
        while True:
            await asyncio.sleep(self.settings.claim_heartbeat_seconds)
            await self.layer.heartbeat_pipeline_documents(
                self.pipeline_id,
                sorted(active_doc_ids),
                stage="embedding",
                worker_id=self.settings.resolved_worker_id,
            )


class ReviewEmbeddingWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        layer: LayerClient,
        embedder: QwenTextEmbedder,
    ) -> None:
        self.settings = settings
        self.database = database
        self.layer = layer
        self.embedder = embedder

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        await run_worker_loop(
            self.process_once,
            poll_seconds=self.settings.worker_poll_seconds,
            stop_event=stop_event,
        )

    async def claim_documents(self) -> list[str]:
        return await self.layer.claim_pipeline_documents(
            self.settings.reviews_pipeline_id,
            limit=self.settings.embedding_claim_size,
            worker_id=self.settings.resolved_worker_id,
            lease_seconds=self.settings.claim_lease_seconds,
            claim_stage="embedding",
            document_id_prefix=REVIEW_EMBED_PREFIX,
        )

    async def release_documents(self, document_ids: list[str]) -> None:
        await self.layer.release_pipeline_documents(
            self.settings.reviews_pipeline_id,
            document_ids,
            from_stage="embedding",
            worker_id=self.settings.resolved_worker_id,
        )

    async def release_document(self, document_id: str) -> None:
        await self.release_documents([document_id])

    async def fail_documents(self, document_ids: list[str]) -> None:
        await self.layer.fail_pipeline_documents(
            self.settings.reviews_pipeline_id,
            document_ids,
            from_stage="embedding",
            worker_id=self.settings.resolved_worker_id,
        )

    async def fail_document(self, document_id: str) -> None:
        await self.fail_documents([document_id])

    async def complete_documents(self, document_ids: list[str]) -> None:
        await self.layer.complete_pipeline_documents(
            self.settings.reviews_pipeline_id,
            document_ids,
            from_stage="embedding",
            worker_id=self.settings.resolved_worker_id,
        )

    async def process_once(self) -> int:
        doc_ids = await self.claim_documents()
        if not doc_ids:
            return 0
        active_doc_ids = set(doc_ids)
        heartbeat = asyncio.create_task(self.heartbeat_documents(active_doc_ids))
        semaphore = asyncio.Semaphore(self.settings.chunk_fetch_concurrency)

        async def prepare(doc_id: str) -> tuple[str, list[tuple[str, dict[str, Any]]]] | None:
            try:
                async with semaphore:
                    chunks = await self.layer.get_chunks(
                        self.settings.reviews_pipeline_id, doc_id
                    )
                if not chunks:
                    await self.fail_document(doc_id)
                    active_doc_ids.discard(doc_id)
                    return None
                raw = chunks[0]
                metadata = raw.get("metadata") or {}
                text = raw.get("text") or ""
                asin = str(metadata.get("asin") or "")
                review_id = str(metadata.get("review_id") or doc_id)
                if not asin or not text.strip():
                    await self.fail_document(doc_id)
                    active_doc_ids.discard(doc_id)
                    return None
                text_chunks = self.embedder.chunk_text(
                    text,
                    chunk_tokens=self.settings.review_chunk_tokens,
                    chunk_overlap=self.settings.review_chunk_overlap,
                )
                if not text_chunks:
                    await self.fail_document(doc_id)
                    active_doc_ids.discard(doc_id)
                    return None
                namespace = review_namespace_for(
                    asin,
                    namespace_base=self.settings.reviews_namespace_base,
                    shard_count=self.settings.reviews_namespace_shard_count,
                )
                attrs = [
                    (
                        chunk_text,
                        review_vector_attributes(
                            metadata,
                            doc_id,
                            chunk_idx=idx,
                            text_chunk=chunk_text,
                        ),
                    )
                    for idx, chunk_text in enumerate(text_chunks)
                ]
                vector_items = [
                    (
                        f"{review_id}:chunk:{idx:04d}",
                        {"id": f"{review_id}:chunk:{idx:04d}", "attributes": attr},
                    )
                    for idx, (_chunk_text, attr) in enumerate(attrs)
                ]
                return namespace, vector_items
            except Exception:
                logger.exception("failed to prepare review document", extra={"doc_id": doc_id})
                await self.release_document(doc_id)
                active_doc_ids.discard(doc_id)
                return None

        logger.info("claimed %s pending review documents for embedding", len(doc_ids))
        try:
            prepared = await asyncio.gather(*(prepare(doc_id) for doc_id in doc_ids))
            by_namespace: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
            doc_vectors: dict[str, list[dict[str, Any]]] = {}
            for doc_id, item in zip(doc_ids, prepared, strict=True):
                if item is None:
                    continue
                namespace, vector_items = item
                doc_vectors[doc_id] = [upsert for _vector_id, upsert in vector_items]
                for vector_id, upsert in vector_items:
                    by_namespace.setdefault(namespace, []).append(
                        (doc_id, vector_id, upsert)
                    )

            written = 0
            for namespace, namespace_items in by_namespace.items():
                for chunk in batches(
                    namespace_items, self.settings.review_embedding_batch_size
                ):
                    texts = [
                        str(item[2]["attributes"]["text_chunk"])
                        for item in chunk
                    ]
                    try:
                        vectors = self.embedder.encode_texts(texts)
                    except Exception:
                        logger.exception("Qwen review embedding batch failed")
                        batch_doc_ids = sorted({item[0] for item in chunk})
                        await self.release_documents(batch_doc_ids)
                        active_doc_ids.difference_update(batch_doc_ids)
                        continue
                    for (_doc_id, _vector_id, upsert), vector in zip(
                        chunk, vectors, strict=True
                    ):
                        upsert["vector"] = vector

            complete_doc_ids: list[str] = []
            for doc_id, upsert_items in doc_vectors.items():
                if not upsert_items or any("vector" not in item for item in upsert_items):
                    continue
                namespace = review_namespace_for(
                    str(upsert_items[0]["attributes"]["asin"]),
                    namespace_base=self.settings.reviews_namespace_base,
                    shard_count=self.settings.reviews_namespace_shard_count,
                )
                try:
                    await self.layer.upsert_vectors(namespace, upsert_items)
                    written += len(upsert_items)
                    complete_doc_ids.append(doc_id)
                except Exception:
                    logger.exception("failed to upsert review vector batch")
                    await self.release_document(doc_id)
                    active_doc_ids.discard(doc_id)

            await self.complete_documents(complete_doc_ids)
            active_doc_ids.difference_update(complete_doc_ids)
            return written
        except asyncio.CancelledError:
            if active_doc_ids:
                await self.release_documents(sorted(active_doc_ids))
                active_doc_ids.clear()
            raise
        except Exception:
            if active_doc_ids:
                await self.release_documents(sorted(active_doc_ids))
                active_doc_ids.clear()
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def heartbeat_documents(self, active_doc_ids: set[str]) -> None:
        while True:
            await asyncio.sleep(self.settings.claim_heartbeat_seconds)
            await self.layer.heartbeat_pipeline_documents(
                self.settings.reviews_pipeline_id,
                sorted(active_doc_ids),
                stage="embedding",
                worker_id=self.settings.resolved_worker_id,
            )
