"""Worker-level tests for the trending reduce (`indexer/trending.py`)."""

from __future__ import annotations

import unittest

from trending import TrendingContext, run_trending_once

from _fakes import FakeLayerClient, make_settings


def make_ctx(layer: FakeLayerClient | None = None, **settings_overrides) -> TrendingContext:
    return TrendingContext(
        settings=make_settings(**settings_overrides),
        layer=layer or FakeLayerClient(),
    )


class TrendingReduceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_search_history_with_first_page_tag(self) -> None:
        """The history read filters on settings.trending_history_tag (page:first)."""
        layer = FakeLayerClient()
        ctx = make_ctx(layer)

        await run_trending_once(ctx)

        self.assertEqual(len(layer.list_search_history_calls), 1)
        call = layer.list_search_history_calls[0]
        self.assertEqual(call["namespace"], "amazon-products")
        self.assertEqual(call["tags"], ["page:first"])
        self.assertEqual(call["limit"], 500)
        self.assertIsInstance(call["from_"], str)
        self.assertIsInstance(call["to"], str)

    async def test_phase1_skips_clickstream_read(self) -> None:
        """With trending_quality_weight=0, list_clickstream is never called."""
        layer = FakeLayerClient()
        layer.search_history_events = [
            {"trace_id": "t1", "raw_query": "lamp", "top_result_ids": ["B1"]},
            {"trace_id": "t2", "raw_query": "lamp", "top_result_ids": ["B2"]},
        ]
        ctx = make_ctx(layer)

        await run_trending_once(ctx)

        self.assertEqual(layer.list_clickstream_calls, [])

    async def test_writes_one_row_per_trending_query(self) -> None:
        """Aggregated entries are upserted into <ns>-trending; returns the count."""
        layer = FakeLayerClient()
        layer.search_history_events = [
            {"trace_id": "t1", "raw_query": "Lamp", "top_result_ids": ["B1"]},
            {"trace_id": "t2", "raw_query": " lamp ", "top_result_ids": ["B2"]},
            {"trace_id": "t3", "raw_query": "headphones", "top_result_ids": ["B3"]},
            {"trace_id": "t4", "raw_query": "headphones", "top_result_ids": ["B4"]},
        ]
        ctx = make_ctx(layer)

        written = await run_trending_once(ctx)

        self.assertEqual(written, 2)
        self.assertEqual(len(layer.upsert_calls), 1)
        call = layer.upsert_calls[0]
        self.assertEqual(call["namespace"], "amazon-products-trending")
        rows = call["body"]["upsert_rows"]
        self.assertEqual({row["query"] for row in rows}, {"lamp", "headphones"})
        self.assertTrue(all(row["_derived_from"] == "amazon-products" for row in rows))
        self.assertTrue(all(row["_derived_by"] == "hev-shop-trending" for row in rows))

    async def test_empty_history_writes_nothing(self) -> None:
        """No searches in the window ⇒ no upsert, returns 0."""
        layer = FakeLayerClient()
        ctx = make_ctx(layer)

        written = await run_trending_once(ctx)

        self.assertEqual(written, 0)
        self.assertEqual(layer.upsert_calls, [])

    async def test_phase2_reads_clickstream_when_quality_weighted(self) -> None:
        """trending_quality_weight>0 ⇒ list_clickstream is read and joined by trace_id."""
        layer = FakeLayerClient()
        layer.search_history_events = [
            {"trace_id": "t1", "raw_query": "lamp", "top_result_ids": ["B1", "B2"]},
            {"trace_id": "t2", "raw_query": "lamp", "top_result_ids": ["B3", "B4"]},
        ]
        layer.clickstream_events = [
            {"trace_id": "t1", "doc_id": "B1"},
            {"trace_id": "other", "doc_id": "B9"},
        ]
        ctx = make_ctx(layer, trending_quality_weight=1.0)

        written = await run_trending_once(ctx)

        self.assertEqual(written, 1)
        self.assertEqual(len(layer.list_clickstream_calls), 1)
        call = layer.list_clickstream_calls[0]
        self.assertEqual(call["namespace"], "amazon-products")
        self.assertEqual(call["limit"], 500)
        rows = layer.upsert_calls[0]["body"]["upsert_rows"]
        self.assertGreater(rows[0]["ndcg"], 0)


if __name__ == "__main__":
    unittest.main()
