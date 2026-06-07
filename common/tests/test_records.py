import unittest

from hev_shop_common.records import ProductRecord, dedupe_categories, product_vector_attributes


class InputNormalizerTests(unittest.TestCase):
    def test_dedupe_categories_trims_and_preserves_order(self):
        self.assertEqual(
            dedupe_categories([" Books ", "Electronics", "books"]),
            ["Books", "Electronics"],
        )


class ProductRecordTests(unittest.TestCase):
    def test_product_attributes_are_json_ready(self):
        product = ProductRecord(
            asin="B0123",
            category="Electronics",
            image_url="https://example.test/camera.jpg",
            title="Camera",
            description="Small camera",
            avg_rating=3.5,
            rating_count=6,
        )

        attrs = product.attributes()

        self.assertEqual(product.document_text(), "Camera\nSmall camera")
        self.assertEqual(attrs["image_url"], "https://example.test/camera.jpg")
        self.assertEqual(
            set(attrs),
            {
                "asin",
                "category",
                "image_url",
                "title",
                "description",
                "avg_rating",
                "rating_count",
            },
        )


class ProductVectorAttributeTests(unittest.TestCase):
    def test_avoids_numeric_schema_conflicts(self):
        attrs = product_vector_attributes(
            {
                "asin": "B0123",
                "title": "Camera",
                "category": "Electronics",
                "description": "Small camera",
                "image_url": "https://example.test/camera.jpg",
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
        self.assertEqual(
            set(attrs),
            {
                "asin",
                "title",
                "category",
                "description",
                "image_url",
                "avg_rating_txt",
                "rating_cnt_txt",
            },
        )


if __name__ == "__main__":
    unittest.main()
