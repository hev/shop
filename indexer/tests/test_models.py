import unittest
from datetime import datetime, timezone

from app.models import IndexRequest
from app.records import ReviewRecord, dedupe_categories, normalize_review_tags


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

    def test_review_record_attributes_are_json_ready(self):
        review = ReviewRecord(
            asin="A1",
            review_id="r1",
            category="Electronics",
            rating=4,
            title="Good",
            text="Worked well",
            helpful_vote=3,
            verified_purchase=True,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(review.document_text(), "Good\nWorked well")
        self.assertEqual(review.attributes()["timestamp"], "2024-01-01T00:00:00+00:00")

    def test_normalize_review_tags_allows_only_phase_one_schema(self):
        self.assertEqual(
            normalize_review_tags(
                ["Value Leader", "not-a-tag", "Value Leader", "Overpriced"]
            ),
            ["Value Leader", "Overpriced"],
        )


if __name__ == "__main__":
    unittest.main()
