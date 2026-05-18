from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4


EXTRACTION_JOB_CHUNK_ID = "extraction-job"


@dataclass(frozen=True)
class ExtractionJob:
    id: str
    pipeline_id: str
    namespace: str
    category: str
    row_offset: int
    row_limit: int
    job_kind: str = "index"
    target_asins: tuple[str, ...] | None = None
    reviews_per_product: int | None = None
    max_total_reviews: int | None = None
    review_stages: tuple[str, ...] | None = None


def build_index_jobs(
    *,
    pipeline_id: str,
    namespace: str,
    category: str,
    count: int,
    job_size: int,
) -> list[ExtractionJob]:
    if count == 0:
        return []
    if count < -1:
        raise ValueError("count must be -1 or non-negative")
    if job_size <= 0:
        raise ValueError("job_size must be positive")

    if count == -1:
        return [
            ExtractionJob(
                id=new_extraction_job_id("index"),
                pipeline_id=pipeline_id,
                namespace=namespace,
                category=category,
                row_offset=0,
                row_limit=-1,
            )
        ]

    jobs: list[ExtractionJob] = []
    offset = 0
    while offset < count:
        limit = min(job_size, count - offset)
        jobs.append(
            ExtractionJob(
                id=new_extraction_job_id("index"),
                pipeline_id=pipeline_id,
                namespace=namespace,
                category=category,
                row_offset=offset,
                row_limit=limit,
            )
        )
        offset += limit
    return jobs


def build_backfill_job(
    *,
    pipeline_id: str,
    namespace: str,
    category: str,
    product_limit: int,
    target_asins: list[str] | None,
    reviews_per_product: int | None,
    max_total_reviews: int | None,
    stages: list[str],
) -> ExtractionJob:
    if product_limit < -1:
        raise ValueError("product_limit must be -1 or non-negative")
    if not stages:
        raise ValueError("stages must contain at least one entry")
    return ExtractionJob(
        id=new_extraction_job_id("backfill"),
        pipeline_id=pipeline_id,
        namespace=namespace,
        category=category,
        row_offset=0,
        row_limit=product_limit,
        job_kind="backfill",
        target_asins=tuple(target_asins) if target_asins else None,
        reviews_per_product=reviews_per_product,
        max_total_reviews=max_total_reviews,
        review_stages=tuple(stages),
    )


def new_extraction_job_id(kind: str) -> str:
    return f"{kind}:{uuid4().hex}"


def extraction_job_metadata(job: ExtractionJob) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "pipeline_id": job.pipeline_id,
        "namespace": job.namespace,
        "category": job.category,
        "row_offset": job.row_offset,
        "row_limit": job.row_limit,
        "job_kind": job.job_kind,
    }
    if job.target_asins is not None:
        metadata["target_asins"] = list(job.target_asins)
    if job.reviews_per_product is not None:
        metadata["reviews_per_product"] = job.reviews_per_product
    if job.max_total_reviews is not None:
        metadata["max_total_reviews"] = job.max_total_reviews
    if job.review_stages is not None:
        metadata["review_stages"] = list(job.review_stages)
    return metadata


def extraction_job_from_chunks(
    document_id: str, chunks: list[dict[str, Any]]
) -> ExtractionJob:
    if not chunks:
        raise ValueError(f"extraction job {document_id!r} has no chunks")
    metadata = chunks[0].get("metadata") or {}
    return ExtractionJob(
        id=document_id,
        pipeline_id=str(metadata["pipeline_id"]),
        namespace=str(metadata["namespace"]),
        category=str(metadata["category"]),
        row_offset=int(metadata.get("row_offset") or 0),
        row_limit=int(metadata["row_limit"]),
        job_kind=str(metadata.get("job_kind") or "index"),
        target_asins=_string_tuple(metadata.get("target_asins")),
        reviews_per_product=_optional_int(metadata.get("reviews_per_product")),
        max_total_reviews=_optional_int(metadata.get("max_total_reviews")),
        review_stages=_string_tuple(metadata.get("review_stages")),
    )


def _string_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    cleaned = tuple(str(item) for item in value if str(item))
    return cleaned or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
