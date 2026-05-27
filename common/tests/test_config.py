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

    def test_review_aggregate_listing_page_size_uses_new_env_name(self):
        settings = Settings(REVIEW_AGGREGATE_LISTING_PAGE_SIZE="123")

        self.assertEqual(settings.review_aggregate_listing_page_size, 123)

    def test_review_aggregate_listing_page_size_accepts_scan_alias(self):
        settings = Settings(REVIEW_AGGREGATE_SCAN_PAGE_SIZE="456")

        self.assertEqual(settings.review_aggregate_listing_page_size, 456)


if __name__ == "__main__":
    unittest.main()
