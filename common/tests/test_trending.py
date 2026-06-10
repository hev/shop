"""Unit tests for the pure trending reduce (`hev_shop_common.trending`)."""

from __future__ import annotations

from math import isclose

from hev_shop_common.trending import (
    ClickEvent,
    SearchEvent,
    TrendingConfig,
    aggregate_trending,
    dcg,
    idcg,
    ndcg,
    normalize_query,
)


class TestNormalizeQuery:
    def test_casefolds_and_collapses_whitespace(self) -> None:
        """'  Wireless   Headphones ' → 'wireless headphones' (one key)."""
        assert normalize_query("  Wireless   Headphones ") == "wireless headphones"

    def test_drops_empty_and_overlong(self) -> None:
        """Empty/whitespace-only and absurdly long inputs return None."""
        assert normalize_query(" \n\t ") is None
        assert normalize_query("x" * 161) is None


class TestNdcgMath:
    def test_dcg_rewards_higher_ranks(self) -> None:
        """A click at rank 0 contributes more than the same click at rank 5."""
        assert dcg([0]) > dcg([5])

    def test_ndcg_is_one_when_clicks_fill_top_ranks(self) -> None:
        """Clicks at ranks [0,1] with 2 clicks ⇒ ndcg == 1.0 (dcg == idcg)."""
        assert isclose(dcg([0, 1]), idcg(2))
        assert isclose(ndcg([0, 1]), 1.0)

    def test_ndcg_is_zero_with_no_clicks(self) -> None:
        """No clicks ⇒ ndcg == 0.0 (and no divide-by-zero on idcg(0))."""
        assert idcg(0) == 0.0
        assert ndcg([]) == 0.0


class TestAggregate:
    def test_phase1_ranks_by_volume_only(self) -> None:
        """With quality_weight=0, score == count and order is by frequency."""
        entries = aggregate_trending(
            [
                SearchEvent("t1", "desk lamp", ["B1"], 1),
                SearchEvent("t2", "wireless headphones", ["B2"], 2),
                SearchEvent("t3", "wireless  headphones", ["B3"], 3),
            ],
            clicks=[],
            config=TrendingConfig(quality_weight=0, min_count=1, top_n=10),
        )

        assert [entry.query for entry in entries] == [
            "wireless headphones",
            "desk lamp",
        ]
        assert entries[0].count == 2
        assert entries[0].score == 2
        assert entries[0].ndcg == 0

    def test_min_count_floor_hides_rare_queries(self) -> None:
        """A query seen once with min_count=2 does not appear in the output."""
        entries = aggregate_trending(
            [
                SearchEvent("t1", "rare", ["B1"], 1),
                SearchEvent("t2", "common", ["B2"], 2),
                SearchEvent("t3", "common", ["B3"], 3),
            ],
            clicks=[],
            config=TrendingConfig(min_count=2, top_n=10),
        )

        assert [entry.query for entry in entries] == ["common"]

    def test_respects_top_n(self) -> None:
        """More distinct queries than top_n ⇒ exactly top_n rows returned."""
        entries = aggregate_trending(
            [
                SearchEvent("t1", "a", ["B1"], 1),
                SearchEvent("t2", "b", ["B2"], 2),
                SearchEvent("t3", "c", ["B3"], 3),
            ],
            clicks=[],
            config=TrendingConfig(min_count=1, top_n=2),
        )

        assert len(entries) == 2

    def test_phase2_quality_weight_reorders(self) -> None:
        """Equal counts, higher mean NDCG ⇒ ranks first when quality_weight>0."""
        searches = [
            SearchEvent("t1", "lamp", ["L1", "L2", "L3"], 1),
            SearchEvent("t2", "lamp", ["L4", "L5", "L6"], 2),
            SearchEvent("t3", "headphones", ["H1", "H2", "H3"], 3),
            SearchEvent("t4", "headphones", ["H4", "H5", "H6"], 4),
        ]
        clicks = [
            ClickEvent("t1", "L3", 10),
            ClickEvent("t2", "L6", 11),
            ClickEvent("t3", "H1", 12),
            ClickEvent("t4", "H4", 13),
        ]

        entries = aggregate_trending(
            searches,
            clicks,
            config=TrendingConfig(quality_weight=1.0, min_count=1, top_n=10),
        )

        assert [entry.query for entry in entries] == ["headphones", "lamp"]
        assert entries[0].ndcg > entries[1].ndcg

    def test_ignores_clicks_in_phase1(self) -> None:
        """quality_weight=0 ⇒ clicks are not required and do not change order."""
        searches = [
            SearchEvent("t1", "b query", ["B1"], 1),
            SearchEvent("t2", "a query", ["A1"], 2),
        ]
        clicks = [ClickEvent("t2", "A1", 10)]

        entries = aggregate_trending(
            searches,
            clicks,
            config=TrendingConfig(quality_weight=0, min_count=1, top_n=10),
        )

        assert [entry.query for entry in entries] == ["a query", "b query"]
        assert all(entry.ndcg == 0 for entry in entries)
