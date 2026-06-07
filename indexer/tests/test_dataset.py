import unittest

from dataset import (
    dataset_config,
    metadata_url,
    pick_image_url,
    product_from_row,
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


if __name__ == "__main__":
    unittest.main()
