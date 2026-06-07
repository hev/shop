import unittest

from app import IndexRequest
from hev_shop_common.records import dedupe_categories


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


if __name__ == "__main__":
    unittest.main()
