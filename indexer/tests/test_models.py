import unittest
from datetime import datetime, timezone

from app import IndexRequest, default_catalog_run_id
from hev_shop_common.records import dedupe_categories

from extract_chunk import build_index_jobs, extraction_job_from_chunks, extraction_job_metadata


class ModelTests(unittest.TestCase):
    def test_index_request_uses_default_category(self):
        request = IndexRequest()

        self.assertEqual(request.resolved_categories("Electronics"), ["Electronics"])

    def test_index_request_accepts_multi_category_fanout(self):
        request = IndexRequest(
            category="Electronics",
            categories=[
                "Electronics",
                "Home and Kitchen",
                "electronics",
                "Books",
                "",
            ],
        )

        self.assertEqual(
            request.resolved_categories("Electronics"),
            ["Electronics", "Home and Kitchen", "Books"],
        )

    def test_dedupe_categories_trims_and_preserves_order(self):
        self.assertEqual(
            dedupe_categories([" Books ", "Electronics", "books"]),
            ["Books", "Electronics"],
        )

    def test_default_catalog_run_id_uses_utc_date(self):
        self.assertEqual(
            default_catalog_run_id(datetime(2026, 6, 9, 23, tzinfo=timezone.utc)),
            "catalog-2026-06-09",
        )

    def test_index_request_accepts_catalog_run_override(self):
        request = IndexRequest(catalog_run_id=" catalog-2026-06-09 ")

        self.assertEqual(request.resolved_catalog_run_id(), "catalog-2026-06-09")

    def test_extraction_jobs_round_trip_catalog_run_metadata(self):
        jobs = build_index_jobs(
            pipeline_id="hev-shop-product-images",
            namespace="amazon-products",
            category="Electronics",
            count=3,
            job_size=2,
            catalog_run_id="catalog-2026-06-09",
        )

        self.assertEqual(len(jobs), 2)
        metadata = extraction_job_metadata(jobs[0])
        self.assertEqual(metadata["catalog_run_id"], "catalog-2026-06-09")
        decoded = extraction_job_from_chunks(
            jobs[0].id,
            [{"id": "extraction-job", "metadata": metadata}],
        )
        self.assertEqual(decoded.catalog_run_id, "catalog-2026-06-09")


if __name__ == "__main__":
    unittest.main()
