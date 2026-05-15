import unittest

from app.vector_attrs import vector_attributes


class EmbeddingTests(unittest.TestCase):
    def test_vector_attributes_avoid_numeric_schema_conflicts(self):
        attrs = vector_attributes(
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
