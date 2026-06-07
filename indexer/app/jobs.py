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
                id=new_extraction_job_id(),
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
                id=new_extraction_job_id(),
                pipeline_id=pipeline_id,
                namespace=namespace,
                category=category,
                row_offset=offset,
                row_limit=limit,
            )
        )
        offset += limit
    return jobs


def new_extraction_job_id() -> str:
    return f"index:{uuid4().hex}"


def extraction_job_metadata(job: ExtractionJob) -> dict[str, Any]:
    return {
        "pipeline_id": job.pipeline_id,
        "namespace": job.namespace,
        "category": job.category,
        "row_offset": job.row_offset,
        "row_limit": job.row_limit,
    }


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
    )
