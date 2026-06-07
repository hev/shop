from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "hev-shop-indexer"
    # Pod name in cluster (HOSTNAME); the Layer operator does not inject a
    # worker id, so the pod hostname is the stable per-replica identity.
    worker_id: str = Field(
        default="", validation_alias=AliasChoices("WORKER_ID", "HOSTNAME")
    )

    # HEVLAYER_BASE_URL is what the Layer operator injects into Pipeline CRD
    # workers; LAYER_GATEWAY_URL is the name our own Helm chart uses.
    layer_gateway_url: str = Field(
        default="http://localhost:8080",
        validation_alias=AliasChoices("LAYER_GATEWAY_URL", "HEVLAYER_BASE_URL"),
    )
    layer_api_key: str | None = Field(default=None, alias="LAYER_GATEWAY_API_KEY")
    namespace: str = Field(default="amazon-products", alias="TURBOPUFFER_NAMESPACE")
    default_pipeline_id: str = Field(
        default="hev-shop-product-images", alias="PIPELINE_ID"
    )
    extraction_pipeline_id: str = Field(
        default="hev-shop-extraction-jobs", alias="EXTRACTION_PIPELINE_ID"
    )
    default_category: str = Field(default="Electronics", alias="DEFAULT_CATEGORY")
    distance_metric: str = Field(default="cosine_distance", alias="DISTANCE_METRIC")

    hf_dataset: str = Field(
        default="McAuley-Lab/Amazon-Reviews-2023", alias="HF_DATASET"
    )
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")
    data_dir: Path = Field(default=Path("/data"), alias="DATA_DIR")
    dataset_cache_dir: Path = Field(default=Path("/data/dataset"), alias="DATASET_DIR")
    model_cache_dir: Path = Field(default=Path("/data/models"), alias="MODEL_CACHE_DIR")
    api_model_cache_dir: Path | None = Field(
        default=None, alias="API_MODEL_CACHE_DIR"
    )
    prewarm_text_embedder: bool = Field(
        default=True, alias="PREWARM_TEXT_EMBEDDER"
    )
    meta_cache_ttl_seconds: float = Field(default=30.0, alias="META_CACHE_TTL_SECONDS")

    clip_model_name: str = Field(
        default="openai/clip-vit-large-patch14", alias="CLIP_MODEL_NAME"
    )
    clip_device: str = Field(default="auto", alias="CLIP_DEVICE")

    http_timeout_seconds: float = Field(default=300.0, alias="HTTP_TIMEOUT_SECONDS")
    dataset_download_max_attempts: int = Field(
        default=6, alias="DATASET_DOWNLOAD_MAX_ATTEMPTS"
    )
    extraction_job_size: int = Field(default=10_000, alias="EXTRACTION_JOB_SIZE")
    extraction_concurrency: int = Field(default=16, alias="EXTRACTION_CONCURRENCY")
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE")
    embedding_claim_size: int = Field(default=2_000, alias="EMBEDDING_CLAIM_SIZE")
    worker_poll_seconds: float = Field(default=5.0, alias="WORKER_POLL_SECONDS")
    claim_lease_seconds: int = Field(default=900, alias="CLAIM_LEASE_SECONDS")
    claim_heartbeat_seconds: float = Field(default=60.0, alias="CLAIM_HEARTBEAT_SECONDS")

    @field_validator("layer_gateway_url")
    @classmethod
    def trim_gateway_url(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def resolved_worker_id(self) -> str:
        return self.worker_id or "hev-shop-worker"


@lru_cache
def get_settings() -> Settings:
    return Settings()
