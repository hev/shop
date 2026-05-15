import unittest

from app.reviews import (
    review_id_from_work_document,
    review_namespace_for,
    review_work_document_id,
    stable_shard,
)


class ReviewPipelineTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
