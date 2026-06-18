from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from hev_shop_common.config import Settings

logger = logging.getLogger("hev_shop.huggingface_source")

DEFAULT_HF_ENDPOINT = "https://huggingface.co"


@dataclass(frozen=True)
class HuggingFaceSource:
    endpoint: str
    repo: str
    config: str
    revision: str
    token: str | None = None

    @property
    def domain(self) -> str:
        return dataset_domain(self.config)

    @property
    def cache_name(self) -> str:
        revision = safe_cache_token(self.revision)
        return f"meta_{self.domain}.{revision}.jsonl"

    @property
    def url(self) -> str:
        return metadata_url(
            endpoint=self.endpoint,
            repo=self.repo,
            config=self.config,
            revision=self.revision,
        )


def dataset_config(category: str) -> str:
    category = category.strip()
    if category.startswith("raw_meta_"):
        return category
    return f"raw_meta_{category.replace(' ', '_')}"


def dataset_domain(category_or_config: str) -> str:
    config = dataset_config(category_or_config)
    return config.removeprefix("raw_meta_")


def metadata_url(
    repo: str,
    category: str | None = None,
    *,
    endpoint: str = DEFAULT_HF_ENDPOINT,
    config: str | None = None,
    revision: str = "main",
) -> str:
    resolved_config = config or dataset_config(category or "")
    domain = dataset_domain(resolved_config)
    base = endpoint.rstrip("/")
    repo_path = urllib.parse.quote(repo.strip("/"), safe="/")
    revision_path = urllib.parse.quote(revision or "main", safe="")
    return (
        f"{base}/datasets/{repo_path}/resolve/{revision_path}/"
        f"raw/meta_categories/meta_{domain}.jsonl"
    )


class HuggingFaceSourceReader:
    def __init__(self, settings: "Settings") -> None:
        self.settings = settings

    def iter_rows(self, category: str) -> Iterator[dict[str, Any]]:
        source = resolve_source(self.settings, category)
        self.settings.dataset_cache_dir.mkdir(parents=True, exist_ok=True)
        cached_path = self.settings.dataset_cache_dir / source.cache_name
        path = self._ensure_cached(cached_path, source)
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                yield json.loads(line)

    def _ensure_cached(self, cached_path: Path, source: HuggingFaceSource) -> Path:
        if cached_path.exists():
            return cached_path

        cached_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cached_path.with_name(
            f".{cached_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        self._download_with_resume(source, tmp_path)
        if cached_path.exists():
            tmp_path.unlink(missing_ok=True)
        else:
            tmp_path.replace(cached_path)
        return cached_path

    def _download_with_resume(self, source: HuggingFaceSource, dest: Path) -> None:
        max_attempts = max(1, getattr(self.settings, "dataset_download_max_attempts", 6))
        backoff_seconds = 5.0
        chunk_size = 1 << 20

        for attempt in range(1, max_attempts + 1):
            offset = dest.stat().st_size if dest.exists() else 0
            request = urllib.request.Request(source.url)
            if source.token:
                request.add_header("Authorization", f"Bearer {source.token}")
            if offset > 0:
                request.add_header("Range", f"bytes={offset}-")
            mode = "ab" if offset > 0 else "wb"

            try:
                with urllib.request.urlopen(
                    request, timeout=self.settings.http_timeout_seconds
                ) as response:
                    if offset > 0 and response.status not in (206, 200):
                        dest.unlink(missing_ok=True)
                        raise urllib.error.HTTPError(
                            source.url,
                            response.status,
                            "range not honored",
                            response.headers,
                            None,
                        )
                    with dest.open(mode) as file:
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            file.write(chunk)
                logger.info(
                    "downloaded %s to %s (%d bytes, attempt %d)",
                    source.url,
                    dest,
                    dest.stat().st_size,
                    attempt,
                )
                return
            except (urllib.error.URLError, ConnectionError, TimeoutError) as err:
                logger.warning(
                    "download %s attempt %d/%d failed at %d bytes: %s",
                    source.url,
                    attempt,
                    max_attempts,
                    dest.stat().st_size if dest.exists() else 0,
                    err,
                )
                if attempt >= max_attempts:
                    raise
                time.sleep(backoff_seconds * attempt)


def resolve_source(settings: "Settings", category: str) -> HuggingFaceSource:
    source_ref = parse_json_env("HEVLAYER_SOURCE_REF")
    warehouse = parse_json_env("HEVLAYER_WAREHOUSE")
    repo = (
        source_ref.get("repo")
        or source_ref.get("dataset")
        or warehouse.get("repo")
        or settings.hf_dataset
    )
    endpoint = warehouse.get("endpoint") or DEFAULT_HF_ENDPOINT
    config = source_ref.get("config") or dataset_config(category)
    revision = source_ref.get("revision") or "main"
    token = token_from_warehouse(warehouse) or settings.hf_token
    return HuggingFaceSource(
        endpoint=str(endpoint),
        repo=str(repo),
        config=str(config),
        revision=str(revision),
        token=token,
    )


def parse_json_env(name: str) -> dict[str, Any]:
    raw = os.environ.get(name)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("%s is not valid JSON; ignoring", name)
        return {}
    return value if isinstance(value, dict) else {}


def token_from_warehouse(warehouse: dict[str, Any]) -> str | None:
    token_path = warehouse.get("tokenPath")
    if not token_path:
        return None
    try:
        token = Path(str(token_path)).read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("failed to read HuggingFace tokenPath %s", token_path)
        return None
    return token or None


def safe_cache_token(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in value)
