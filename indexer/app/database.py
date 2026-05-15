from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from math import ceil
from typing import Any

import asyncpg


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hev_shop_index_jobs (
    id              BIGSERIAL PRIMARY KEY,
    pipeline_id     TEXT NOT NULL,
    namespace       TEXT NOT NULL,
    category        TEXT NOT NULL,
    row_offset      INT NOT NULL DEFAULT 0,
    row_limit       INT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    retry_count     INT NOT NULL DEFAULT 0,
    max_retries     INT NOT NULL DEFAULT 3,
    processed_count INT NOT NULL DEFAULT 0,
    claimed_by      TEXT,
    claimed_at      TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_hev_shop_jobs_status
    ON hev_shop_index_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS idx_hev_shop_jobs_pipeline
    ON hev_shop_index_jobs (pipeline_id, status);

CREATE TABLE IF NOT EXISTS review_tags (
    asin          TEXT NOT NULL,
    review_id     TEXT NOT NULL,
    tag           TEXT NOT NULL,
    confidence    REAL NOT NULL,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asin, review_id, tag)
);

CREATE INDEX IF NOT EXISTS review_tags_asin_classified_idx
    ON review_tags (asin, classified_at);

CREATE TABLE IF NOT EXISTS review_classifications (
    asin          TEXT NOT NULL,
    review_id     TEXT NOT NULL,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asin, review_id)
);

CREATE INDEX IF NOT EXISTS review_classifications_asin_idx
    ON review_classifications (asin, classified_at);

CREATE TABLE IF NOT EXISTS review_classifier_usage (
    usage_date        DATE PRIMARY KEY,
    request_count     INT NOT NULL DEFAULT 0,
    review_count      INT NOT NULL DEFAULT 0,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@dataclass(frozen=True)
class ExtractionJob:
    id: int
    pipeline_id: str
    namespace: str
    category: str
    row_offset: int
    row_limit: int


class Database:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, database_url: str) -> "Database":
        pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=10)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def ensure_schema(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)

    async def enqueue_index_jobs(
        self,
        *,
        pipeline_id: str,
        namespace: str,
        category: str,
        count: int,
        job_size: int,
        max_retries: int,
    ) -> int:
        if count == 0:
            return 0
        if count < -1:
            raise ValueError("count must be -1 or non-negative")
        if job_size <= 0:
            raise ValueError("job_size must be positive")

        if count == -1:
            jobs = [(pipeline_id, namespace, category, 0, -1, max_retries)]
        else:
            jobs = []
            offset = 0
            while offset < count:
                limit = min(job_size, count - offset)
                jobs.append((pipeline_id, namespace, category, offset, limit, max_retries))
                offset += limit

        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO hev_shop_index_jobs
                    (pipeline_id, namespace, category, row_offset, row_limit, max_retries)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                jobs,
            )
        return len(jobs)

    async def index_job_counts(self, pipeline_id: str) -> dict[str, int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT status, count(*)::int AS count
                FROM hev_shop_index_jobs
                WHERE pipeline_id = $1
                GROUP BY status
                """,
                pipeline_id,
            )
        return {row["status"]: row["count"] for row in rows}

    async def pipeline_namespace(self, pipeline_id: str) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT target_namespace FROM pipelines WHERE id = $1",
                pipeline_id,
            )
        if row is None:
            raise ValueError(f"pipeline {pipeline_id!r} not found")
        return row["target_namespace"]

    async def claim_extraction_job(
        self, worker_id: str, lease_seconds: int
    ) -> ExtractionJob | None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE hev_shop_index_jobs
                    SET status = CASE
                            WHEN retry_count >= max_retries THEN 'failed'
                            ELSE 'retry'
                        END,
                        claimed_by = NULL,
                        claimed_at = NULL,
                        updated_at = now(),
                        error_message = 'claim lease expired'
                    WHERE status = 'running'
                      AND claimed_at < now() - ($1::int * interval '1 second')
                    """,
                    lease_seconds,
                )
                row = await conn.fetchrow(
                    """
                    WITH picked AS (
                        SELECT id
                        FROM hev_shop_index_jobs
                        WHERE status IN ('queued', 'retry')
                          AND retry_count < max_retries
                        ORDER BY created_at, id
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE hev_shop_index_jobs j
                    SET status = 'running',
                        claimed_by = $1,
                        claimed_at = now(),
                        updated_at = now(),
                        error_message = NULL
                    FROM picked
                    WHERE j.id = picked.id
                    RETURNING j.id, j.pipeline_id, j.namespace, j.category,
                              j.row_offset, j.row_limit
                    """,
                    worker_id,
                )
        if row is None:
            return None
        return ExtractionJob(
            id=row["id"],
            pipeline_id=row["pipeline_id"],
            namespace=row["namespace"],
            category=row["category"],
            row_offset=row["row_offset"],
            row_limit=row["row_limit"],
        )

    async def complete_extraction_job(self, job_id: int, processed_count: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE hev_shop_index_jobs
                SET status = 'succeeded',
                    processed_count = $2,
                    completed_at = now(),
                    updated_at = now(),
                    claimed_by = NULL,
                    claimed_at = NULL
                WHERE id = $1
                """,
                job_id,
                processed_count,
            )

    async def fail_extraction_job(self, job_id: int, error_message: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE hev_shop_index_jobs
                SET retry_count = retry_count + 1,
                    status = CASE
                        WHEN retry_count + 1 >= max_retries THEN 'failed'
                        ELSE 'retry'
                    END,
                    error_message = left($2, 2000),
                    updated_at = now(),
                    claimed_by = NULL,
                    claimed_at = NULL
                WHERE id = $1
                """,
                job_id,
                error_message,
            )

    async def heartbeat_extraction_job(self, job_id: int, worker_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE hev_shop_index_jobs
                SET claimed_at = now(),
                    updated_at = now()
                WHERE id = $1
                  AND status = 'running'
                  AND claimed_by = $2
                """,
                job_id,
                worker_id,
            )

    async def release_extraction_job(
        self, job_id: int, worker_id: str, reason: str
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE hev_shop_index_jobs
                SET status = CASE
                        WHEN retry_count >= max_retries THEN 'failed'
                        ELSE 'retry'
                    END,
                    claimed_by = NULL,
                    claimed_at = NULL,
                    error_message = left($3, 2000),
                    updated_at = now()
                WHERE id = $1
                  AND status = 'running'
                  AND claimed_by = $2
                """,
                job_id,
                worker_id,
                reason,
            )

    async def write_review_tags(
        self, rows: list[dict[str, Any]]
    ) -> list[str]:
        if not rows:
            return []
        classified_pairs = sorted(
            {(str(row["asin"]), str(row["review_id"])) for row in rows}
        )
        valid_rows = [
            (
                str(row["asin"]),
                str(row["review_id"]),
                str(row["tag"]),
                float(row["confidence"]),
            )
            for row in rows
        ]
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for asin, review_id in classified_pairs:
                    await conn.execute(
                        """
                        INSERT INTO review_classifications
                            (asin, review_id, classified_at)
                        VALUES ($1, $2, now())
                        ON CONFLICT (asin, review_id) DO UPDATE SET
                            classified_at = now()
                        """,
                        asin,
                        review_id,
                    )
                    await conn.execute(
                        """
                        DELETE FROM review_tags
                        WHERE asin = $1 AND review_id = $2
                        """,
                        asin,
                        review_id,
                    )
                if valid_rows:
                    await conn.executemany(
                        """
                        INSERT INTO review_tags
                            (asin, review_id, tag, confidence, classified_at)
                        VALUES ($1, $2, $3, $4, now())
                        ON CONFLICT (asin, review_id, tag) DO UPDATE SET
                            confidence = EXCLUDED.confidence,
                            classified_at = now()
                        """,
                        valid_rows,
                    )
        return sorted({asin for asin, _review_id in classified_pairs})

    async def replace_review_classification(
        self,
        *,
        asin: str,
        review_id: str,
        tags: list[tuple[str, float]],
    ) -> None:
        rows = [
            {
                "asin": asin,
                "review_id": review_id,
                "tag": tag,
                "confidence": confidence,
            }
            for tag, confidence in tags
        ]
        if rows:
            await self.write_review_tags(rows)
            return
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO review_classifications
                        (asin, review_id, classified_at)
                    VALUES ($1, $2, now())
                    ON CONFLICT (asin, review_id) DO UPDATE SET
                        classified_at = now()
                    """,
                    asin,
                    review_id,
                )
                await conn.execute(
                    """
                    DELETE FROM review_tags
                    WHERE asin = $1 AND review_id = $2
                    """,
                    asin,
                    review_id,
                )

    async def try_reserve_review_classification(
        self,
        *,
        usage_date: date,
        review_count: int,
        daily_review_limit: int,
    ) -> bool:
        if daily_review_limit <= 0:
            return True
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO review_classifier_usage
                        (usage_date, request_count, review_count, updated_at)
                    VALUES ($1, 0, 0, now())
                    ON CONFLICT (usage_date) DO UPDATE SET updated_at = now()
                    RETURNING request_count, review_count
                    """,
                    usage_date,
                )
                used_reviews = int(row["review_count"])
                if used_reviews + review_count > daily_review_limit:
                    return False
                await conn.execute(
                    """
                    UPDATE review_classifier_usage
                    SET request_count = request_count + 1,
                        review_count = review_count + $2,
                        updated_at = now()
                    WHERE usage_date = $1
                    """,
                    usage_date,
                    review_count,
                )
        return True

    async def aggregate_review_tag_attrs(
        self,
        asin: str,
        *,
        min_count: int,
        min_fraction: float,
        sample_count: int,
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            total = await conn.fetchval(
                """
                SELECT count(*)::int
                FROM review_classifications
                WHERE asin = $1
                """,
                asin,
            )
            total = int(total or 0)
            threshold = max(min_count, ceil(total * min_fraction)) if total else min_count
            rows = await conn.fetch(
                """
                SELECT tag, count(*)::int AS count
                FROM review_tags
                WHERE asin = $1
                GROUP BY tag
                HAVING count(*) >= $2
                ORDER BY count(*) DESC, tag
                """,
                asin,
                threshold,
            )
            tags = [row["tag"] for row in rows]
            tag_counts = {row["tag"]: row["count"] for row in rows}
            tag_samples: dict[str, list[str]] = {}
            for tag in tags:
                sample_rows = await conn.fetch(
                    """
                    SELECT review_id
                    FROM review_tags
                    WHERE asin = $1 AND tag = $2
                    ORDER BY confidence DESC, classified_at DESC, review_id
                    LIMIT $3
                    """,
                    asin,
                    tag,
                    sample_count,
                )
                tag_samples[tag] = [row["review_id"] for row in sample_rows]

        attrs: dict[str, Any] = {
            "tags": tags,
            "classified_review_count": total,
            "tag_threshold": threshold,
        }
        # Turbopuffer attribute types are scalars or arrays of scalars — nested
        # objects fail strict validation on patch_rows. JSON-stringify the
        # dict-shaped fields here; the /search and /product handlers decode them
        # back into dicts so consumers see a stable shape.
        if tag_counts:
            attrs["tag_counts"] = json.dumps(tag_counts, separators=(",", ":"))
        if tag_samples:
            attrs["tag_samples"] = json.dumps(tag_samples, separators=(",", ":"))
        return attrs
