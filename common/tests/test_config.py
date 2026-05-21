import unittest

from hev_shop_common.config import Settings


class SettingsTests(unittest.TestCase):
    def test_query_namespace_falls_back_to_write_base(self):
        settings = Settings(REVIEWS_NAMESPACE_BASE="v2-amazon-reviews")

        self.assertEqual(
            settings.resolved_reviews_query_namespace_base, "v2-amazon-reviews"
        )

    def test_query_namespace_uses_explicit_override(self):
        settings = Settings(
            REVIEWS_NAMESPACE_BASE="v3-amazon-reviews",
            REVIEWS_QUERY_NAMESPACE_BASE="v2-amazon-reviews",
        )

        self.assertEqual(
            settings.resolved_reviews_query_namespace_base, "v2-amazon-reviews"
        )
        self.assertEqual(settings.reviews_namespace_base, "v3-amazon-reviews")

    def test_default_namespace_is_v2(self):
        settings = Settings()

        self.assertEqual(settings.reviews_namespace_base, "v2-amazon-reviews")
        self.assertIsNone(settings.reviews_query_namespace_base)


if __name__ == "__main__":
    unittest.main()
