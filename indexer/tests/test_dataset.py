import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.dataset import (
    AmazonProductDataset,
    dataset_config,
    metadata_url,
    pick_image_url,
    product_from_row,
    review_dataset_config,
    review_from_row,
    reviews_url,
)


class DatasetTests(unittest.TestCase):
    def test_dataset_config_accepts_plain_category(self):
        self.assertEqual(dataset_config("Electronics"), "raw_meta_Electronics")
        self.assertEqual(dataset_config("Cell Phones"), "raw_meta_Cell_Phones")

    def test_dataset_config_keeps_raw_meta_prefix(self):
        self.assertEqual(
            dataset_config("raw_meta_Electronics"), "raw_meta_Electronics"
        )

    def test_metadata_url_points_at_raw_meta_jsonl(self):
        self.assertEqual(
            metadata_url("McAuley-Lab/Amazon-Reviews-2023", "Electronics"),
            "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/meta_categories/meta_Electronics.jsonl",
        )

    def test_review_dataset_config_accepts_plain_category(self):
        self.assertEqual(review_dataset_config("Electronics"), "raw_review_Electronics")
        self.assertEqual(review_dataset_config("Cell Phones"), "raw_review_Cell_Phones")

    def test_reviews_url_points_at_raw_review_jsonl(self):
        self.assertEqual(
            reviews_url("McAuley-Lab/Amazon-Reviews-2023", "Electronics"),
            "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main/raw/review_categories/Electronics.jsonl",
        )

    def test_pick_image_url_prefers_high_resolution(self):
        images = [
            {"thumb": "https://example.test/thumb.jpg"},
            {
                "large": "https://example.test/large.jpg",
                "hi_res": "https://example.test/hi-res.jpg",
            },
        ]
        self.assertEqual(pick_image_url(images), "https://example.test/hi-res.jpg")

    def test_product_from_row_normalizes_metadata(self):
        product = product_from_row(
            {
                "parent_asin": "B0123",
                "title": "Camera",
                "description": ["Small", "Waterproof"],
                "price": "$19.99",
                "average_rating": "4.5",
                "rating_number": "1,234",
                "images": [{"hi_res": "https://example.test/camera.jpg"}],
            },
            "Electronics",
        )

        self.assertIsNotNone(product)
        assert product is not None
        self.assertEqual(product.asin, "B0123")
        self.assertEqual(product.price, 19.99)
        self.assertEqual(product.avg_rating, 4.5)
        self.assertEqual(product.rating_count, 1234)
        self.assertEqual(product.image_url, "https://example.test/camera.jpg")

    def test_review_from_row_normalizes_review(self):
        review = review_from_row(
            {
                "parent_asin": "B0123",
                "user_id": "U1",
                "timestamp": 1700000000000,
                "rating": "5.0",
                "title": "Great",
                "text": "Loved it",
                "helpful_vote": "12",
                "verified_purchase": "true",
            },
            "Electronics",
        )

        self.assertIsNotNone(review)
        assert review is not None
        self.assertEqual(review.asin, "B0123")
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.helpful_vote, 12)
        self.assertTrue(review.verified_purchase)
        self.assertIn("Loved it", review.document_text())

    def test_iter_reviews_for_asins_keeps_recent_and_helpful_caps(self):
        rows = [
            {
                "parent_asin": "A",
                "user_id": "old",
                "timestamp": 1000,
                "text": "old",
                "helpful_vote": 100,
            },
            {
                "parent_asin": "A",
                "user_id": "new",
                "timestamp": 3000,
                "text": "new",
                "helpful_vote": 1,
            },
            {
                "parent_asin": "A",
                "user_id": "middle",
                "timestamp": 2000,
                "text": "middle",
                "helpful_vote": 2,
            },
            {
                "parent_asin": "B",
                "user_id": "other",
                "timestamp": 4000,
                "text": "other asin",
                "helpful_vote": 999,
            },
        ]

        class FakeDataset(AmazonProductDataset):
            def _iter_review_rows(self, category, cached_path):
                yield from rows

        with TemporaryDirectory() as tmp:
            settings = SimpleNamespace(
                dataset_cache_dir=Path(tmp),
                hf_dataset="repo",
                hf_token=None,
                http_timeout_seconds=1,
            )
            dataset = FakeDataset(settings)
            reviews = list(
                dataset.iter_reviews_for_asins(
                    category="Electronics",
                    asins={"A"},
                    recent_limit=1,
                    helpful_limit=1,
                )
            )

        self.assertEqual({review.text for review in reviews}, {"old", "new"})


if __name__ == "__main__":
    unittest.main()
