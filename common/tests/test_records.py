import unittest

from hev_shop_common.records import (
    product_vector_attributes,
    review_id_from_work_document,
    review_namespace_for,
    review_work_document_id,
    stable_shard,
)


class StableShardTests(unittest.TestCase):
    def test_stable_shard_is_bounded_and_repeatable(self):
        first = stable_shard("B0123", 16)
        second = stable_shard("B0123", 16)

        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 16)

    def test_review_namespace_uses_hash_shard_suffix(self):
        namespace = review_namespace_for(
            "B0123", namespace_base="amazon-reviews", shard_count=16
        )

        self.assertRegex(namespace, r"^amazon-reviews-\d+$")

    def test_review_work_document_ids_are_reversible(self):
        doc_id = review_work_document_id("classify", "r123")

        self.assertEqual(doc_id, "review-classify:r123")
        self.assertEqual(review_id_from_work_document(doc_id), "r123")


class ProductVectorAttributeTests(unittest.TestCase):
    def test_avoids_numeric_schema_conflicts(self):
        attrs = product_vector_attributes(
            {
                "asin": "B0123",
                "title": "Camera",
                "category": "Electronics",
                "description": "Small camera",
                "image_url": "https://example.test/camera.jpg",
                "image_path": "/data/images/B0123.jpg",
                "avg_rating": 3.5,
                "rating_count": 6,
            },
            "fallback",
        )

        self.assertEqual(attrs["asin"], "B0123")
        self.assertEqual(attrs["avg_rating_txt"], "3.5")
        self.assertEqual(attrs["rating_cnt_txt"], "6")
        self.assertNotIn("avg_rating", attrs)
        self.assertNotIn("rating_count", attrs)


if __name__ == "__main__":
    unittest.main()
