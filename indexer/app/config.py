from functools import lru_cache
from pathlib import Path
from typing import Callable, Literal

from dataclasses import dataclass
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class PipelineConfig:
    pipeline_id: str
    namespace_resolver: Callable[[dict[str, object], str], str]
    vector_attrs: Callable[[dict[str, object], str], dict[str, object]]
    embedder_type: Literal["clip-image", "qwen-text"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "hev-shop-indexer"
    worker_type: str = Field(default="api", alias="WORKER_TYPE")
    worker_id: str = Field(default="", alias="WORKER_ID")

    layer_gateway_url: str = Field(
        default="http://localhost:8080", alias="LAYER_GATEWAY_URL"
    )
    namespace: str = Field(default="amazon-products", alias="TURBOPUFFER_NAMESPACE")
    default_pipeline_id: str = Field(
        default="hev-shop-product-images", alias="PIPELINE_ID"
    )
    extraction_pipeline_id: str = Field(
        default="hev-shop-extraction-jobs", alias="EXTRACTION_PIPELINE_ID"
    )
    reviews_pipeline_id: str = Field(
        default="hev-shop-reviews", alias="REVIEWS_PIPELINE_ID"
    )
    review_aggregate_pipeline_id: str = Field(
        default="hev-shop-review-tags", alias="REVIEWS_AGGREGATE_PIPELINE_ID"
    )
    # Review namespaces are versioned by prefix so we can swap embedding
    # models without overwriting the existing corpus. To hot-swap:
    #   1. Bump `reviews_namespace_base` to a new version (e.g. v3-amazon-reviews).
    #      Workers will write the re-embedded corpus to the new prefix.
    #   2. Leave `reviews_query_namespace_base` pinned to the old prefix on the
    #      API pod so reads keep hitting the populated namespace.
    #   3. Requeue review docs; wait for backfill to drain.
    #   4. Unset `reviews_query_namespace_base` (or set it to the new prefix) on
    #      the API. Reads cut over.
    #   5. Delete the old namespaces.
    reviews_namespace_base: str = Field(
        default="v2-amazon-reviews", alias="REVIEWS_NAMESPACE_BASE"
    )
    reviews_query_namespace_base: str | None = Field(
        default=None, alias="REVIEWS_QUERY_NAMESPACE_BASE"
    )
    reviews_namespace_shard_count: int = Field(
        default=16, alias="REVIEWS_NAMESPACE_SHARD_COUNT"
    )
    default_category: str = Field(default="Electronics", alias="DEFAULT_CATEGORY")
    distance_metric: str = Field(default="cosine_distance", alias="DISTANCE_METRIC")

    hf_dataset: str = Field(
        default="McAuley-Lab/Amazon-Reviews-2023", alias="HF_DATASET"
    )
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")
    data_dir: Path = Field(default=Path("/data"), alias="DATA_DIR")
    dataset_cache_dir: Path = Field(default=Path("/data/dataset"), alias="DATASET_DIR")
    image_dir: Path = Field(default=Path("/data/images"), alias="IMAGE_DIR")
    model_cache_dir: Path = Field(default=Path("/data/models"), alias="MODEL_CACHE_DIR")
    api_model_cache_dir: Path | None = Field(
        default=None, alias="API_MODEL_CACHE_DIR"
    )
    prewarm_text_embedder: bool = Field(
        default=True, alias="PREWARM_TEXT_EMBEDDER"
    )
    # Review-query embedding uses Qwen3-Embedding-8B, which needs ~32 GB on
    # CPU and is only viable on the GPU review-embed worker. The API pod
    # ships with the same image but should NOT lazy-load it on demand
    # (doing so triggers a liveness-probe death loop). Set to false in the
    # api deployment; left true so local dev / GPU-equipped boxes still work.
    api_review_search_enabled: bool = Field(
        default=True, alias="API_REVIEW_SEARCH_ENABLED"
    )
    meta_cache_ttl_seconds: float = Field(default=30.0, alias="META_CACHE_TTL_SECONDS")

    # CLIP ViT-L/14 has 768-dimensional image features, matching the current
    # hev-shop design doc. The model name is configurable for smaller local runs.
    clip_model_name: str = Field(
        default="openai/clip-vit-large-patch14", alias="CLIP_MODEL_NAME"
    )
    clip_device: str = Field(default="auto", alias="CLIP_DEVICE")
    review_embedding_model_name: str = Field(
        default="Qwen/Qwen3-Embedding-8B", alias="REVIEW_EMBEDDING_MODEL_NAME"
    )
    review_embedding_device: str = Field(default="auto", alias="REVIEW_EMBEDDING_DEVICE")
    review_chunk_tokens: int = Field(default=256, alias="REVIEW_CHUNK_TOKENS")
    review_chunk_overlap: int = Field(default=32, alias="REVIEW_CHUNK_OVERLAP")

    http_timeout_seconds: float = Field(default=300.0, alias="HTTP_TIMEOUT_SECONDS")
    # Two-stage extraction: HF JSONL files are downloaded once to
    # /data/dataset (PVC-shared across workers) with resumable retries,
    # then every backfill reads from local disk. This setting caps the
    # retry count on the download leg.
    dataset_download_max_attempts: int = Field(
        default=6, alias="DATASET_DOWNLOAD_MAX_ATTEMPTS"
    )
    extraction_job_size: int = Field(default=10_000, alias="EXTRACTION_JOB_SIZE")
    image_download_concurrency: int = Field(default=8, alias="IMAGE_DOWNLOAD_CONCURRENCY")
    extraction_concurrency: int = Field(default=16, alias="EXTRACTION_CONCURRENCY")
    review_stage_concurrency: int = Field(default=16, alias="REVIEW_STAGE_CONCURRENCY")
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE")
    review_embedding_batch_size: int = Field(
        default=4, alias="REVIEW_EMBEDDING_BATCH_SIZE"
    )
    embedding_claim_size: int = Field(default=2_000, alias="EMBEDDING_CLAIM_SIZE")
    vector_upsert_batch_size: int = Field(default=10_000, alias="VECTOR_UPSERT_BATCH_SIZE")
    # Aggregate-worker batches expand into one review-namespace scan per ASIN
    # plus one PATCH call, so they need a smaller cap than the embed-side
    # vector upserts. Sized to fit comfortably under the 60s ALB request limit.
    review_aggregate_batch_size: int = Field(default=200, alias="REVIEW_AGGREGATE_BATCH_SIZE")
    review_aggregate_scan_page_size: int = Field(
        default=10_000, alias="REVIEW_AGGREGATE_SCAN_PAGE_SIZE"
    )
    chunk_fetch_concurrency: int = Field(default=32, alias="CHUNK_FETCH_CONCURRENCY")
    # Per-doc upsert calls in `process_embed_reviews` are issued in parallel
    # via asyncio.gather under this semaphore. Sequential upserts dominated
    # wall-clock time at ~200 ms/doc; 32 concurrent cuts a 2k-doc batch's
    # upsert phase from ~7 min to ~30 s, which also keeps the claim lease
    # from expiring mid-batch.
    review_upsert_concurrency: int = Field(default=32, alias="REVIEW_UPSERT_CONCURRENCY")
    cleanup_embedded_images: bool = Field(default=True, alias="CLEANUP_EMBEDDED_IMAGES")
    worker_poll_seconds: float = Field(default=5.0, alias="WORKER_POLL_SECONDS")
    claim_lease_seconds: int = Field(default=900, alias="CLAIM_LEASE_SECONDS")
    claim_heartbeat_seconds: float = Field(default=60.0, alias="CLAIM_HEARTBEAT_SECONDS")
    max_job_retries: int = Field(default=3, alias="MAX_JOB_RETRIES")
    review_classification_batch_size: int = Field(
        default=8, alias="REVIEW_CLASSIFICATION_BATCH_SIZE"
    )
    review_recent_cap_per_product: int = Field(
        default=200, alias="REVIEW_RECENT_CAP_PER_PRODUCT"
    )
    review_helpful_cap_per_product: int = Field(
        default=200, alias="REVIEW_HELPFUL_CAP_PER_PRODUCT"
    )
    review_tag_min_count: int = Field(default=3, alias="REVIEW_TAG_MIN_COUNT")
    review_tag_min_fraction: float = Field(default=0.05, alias="REVIEW_TAG_MIN_FRACTION")
    review_tag_sample_count: int = Field(default=3, alias="REVIEW_TAG_SAMPLE_COUNT")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model: str = Field(
        default="google/gemini-2.0-flash-lite-001", alias="OPENROUTER_MODEL"
    )
    openrouter_referer: str | None = Field(default=None, alias="OPENROUTER_REFERER")
    openrouter_app_title: str = Field(default="hev-shop", alias="OPENROUTER_APP_TITLE")
    openrouter_max_retries: int = Field(default=3, alias="OPENROUTER_MAX_RETRIES")

    @field_validator("layer_gateway_url")
    @classmethod
    def trim_gateway_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("openrouter_base_url")
    @classmethod
    def trim_openrouter_url(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def resolved_worker_id(self) -> str:
        if self.worker_id:
            return self.worker_id
        return f"{self.worker_type}-worker"

    @property
    def resolved_reviews_query_namespace_base(self) -> str:
        return self.reviews_query_namespace_base or self.reviews_namespace_base


@lru_cache
def get_settings() -> Settings:
    return Settings()
