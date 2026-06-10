"""Trending-search scoring: the pure reduce over search-history + clickstream.

RFC 0040 (`../layer/docs/rfcs/0040-trending-searches-reduce-udfs.md`) splits the
storefront's single "recent searches" surface into two honest reads: *personal
recent* (this browser's queries → client-side localStorage) and **Trending**
(everyone's queries → a Layer reduce UDF). This module is the pure,
side-effect-free core of that reduce: given the search-history (and, in Phase 2,
clickstream) events for a window, it produces the ranked `TrendingEntry` rows the
worker materializes into the `<ns>-trending` namespace.

It lives in `hev_shop_common` rather than in the worker so the math is
unit-testable without a gateway and reusable by any future reduce (top
categories, popularity priors). The worker (`indexer/trending.py`) owns the I/O
— the search-history/clickstream reads and the namespace upsert via the injected
hev layer client; this module owns only the aggregation.

Scoring (RFC 0040 §5), per normalized query `q`:

    count(q) = number of searches with that normalized query
    ndcg(q)  = mean NDCG over those searches (Phase 2; 0 in Phase 1)
    score(q) = count(q) * (1 + W * ndcg(q))

`W` (`TrendingConfig.quality_weight`) is 0 in Phase 1 — pure volume trending,
no click attribution required — and turned up in Phase 2 once clicks are
attributable to the search that produced them (shared `trace_id`).

See `docs/TRENDING_DESIGN.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import log2
from typing import Iterable

MAX_QUERY_CHARS = 160
MAX_SAMPLE_TOP_IDS = 5


def normalize_query(raw: str) -> str | None:
    """Normalize a raw query into the aggregation key, or None to drop it.

    Lowercase, collapse internal whitespace, strip. Returns None for empty or
    over-long inputs so junk and accidental pastes never become a trend.
    (RFC 0040 §5: "Normalize each raw_query into a key q".)
    """
    normalized = " ".join(raw.casefold().split())
    if not normalized or len(normalized) > MAX_QUERY_CHARS:
        return None
    return normalized


def dcg(clicked_ranks: Iterable[int]) -> float:
    """Discounted cumulative gain over the 0-based ranks of clicked results.

    DCG = Σ 1 / log2(rank + 2)  (binary relevance: a click is relevance 1).
    """
    return sum(
        1.0 / log2(rank + 2)
        for rank in clicked_ranks
        if isinstance(rank, int) and rank >= 0
    )


def idcg(num_clicks: int) -> float:
    """Ideal DCG: the DCG if all `num_clicks` clicks landed at the top ranks.

    IDCG = Σ_{i<num_clicks} 1 / log2(i + 2). Used to normalize `dcg` into [0,1].
    """
    if num_clicks <= 0:
        return 0.0
    return sum(1.0 / log2(i + 2) for i in range(num_clicks))


def ndcg(clicked_ranks: Iterable[int]) -> float:
    """NDCG = dcg(clicked_ranks) / idcg(#clicks); 0 when there were no clicks."""
    ranks = [rank for rank in clicked_ranks if isinstance(rank, int) and rank >= 0]
    ideal = idcg(len(ranks))
    if ideal == 0:
        return 0.0
    return dcg(ranks) / ideal


@dataclass(frozen=True)
class SearchEvent:
    """One search-history entry, projected to what the reduce needs.

    `top_result_ids` is the served ranking (rank order, ~top 10) — the join
    target for clickstream attribution. `trace_id` is the clickstream join key.
    """

    trace_id: str
    raw_query: str
    top_result_ids: list[str]
    timestamp_ms: int


@dataclass(frozen=True)
class ClickEvent:
    """One clickstream entry: a document fetch attributed to a search by trace_id."""

    trace_id: str
    doc_id: str
    timestamp_ms: int


@dataclass(frozen=True)
class TrendingEntry:
    """One materialized trending row, upserted as a doc in `<ns>-trending`.

    Mirrors the storefront's `TrendingEntry` HTTP shape (`search/models.py`) and
    the doc attributes in RFC 0040 §6.
    """

    query: str
    count: int
    score: float
    ndcg: float = 0.0
    sample_top_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TrendingConfig:
    """Knobs for the reduce. Defaults are Phase 1 (frequency-only)."""

    # W in score(q) = count(q) * (1 + W * ndcg(q)). 0 ⇒ pure volume (Phase 1).
    quality_weight: float = 0.0
    # Privacy floor (RFC 0040 §risks): a query must appear at least this many
    # times before it can surface, so a single rare query never trends verbatim.
    min_count: int = 2
    # How many rows to materialize.
    top_n: int = 12


def aggregate_trending(
    searches: Iterable[SearchEvent],
    clicks: Iterable[ClickEvent],
    config: TrendingConfig,
) -> list[TrendingEntry]:
    """Reduce a window of events into the top-N trending entries.

    1. Normalize each search's `raw_query`; drop the ones `normalize_query`
       rejects. Group searches by the normalized key.
    2. Phase 2 only: index `clicks` by `trace_id`; per search, map each clicked
       `doc_id` to its rank in `top_result_ids` and compute `ndcg`. In Phase 1
       (`quality_weight == 0`) skip this entirely — `clicks` may be empty.
    3. score(q) = count(q) * (1 + W * mean_ndcg(q)); apply the `min_count`
       floor; return the top `top_n` by score (descending), each with a small
       `sample_top_ids` for the UI.

    Pure: no I/O, deterministic given its inputs (sort ties broken by query).
    """
    if config.top_n <= 0:
        return []

    grouped: dict[str, list[SearchEvent]] = {}
    for search in searches:
        query = normalize_query(search.raw_query)
        if query is None:
            continue
        grouped.setdefault(query, []).append(search)

    clicks_by_trace: dict[str, list[ClickEvent]] = {}
    if config.quality_weight > 0:
        for click in clicks:
            clicks_by_trace.setdefault(click.trace_id, []).append(click)

    entries: list[TrendingEntry] = []
    for query, query_searches in grouped.items():
        count = len(query_searches)
        if count < config.min_count:
            continue

        mean_ndcg = 0.0
        if config.quality_weight > 0:
            ndcgs: list[float] = []
            for search in query_searches:
                rank_by_doc = {
                    doc_id: index for index, doc_id in enumerate(search.top_result_ids)
                }
                clicked_ranks = [
                    rank_by_doc[click.doc_id]
                    for click in clicks_by_trace.get(search.trace_id, [])
                    if click.doc_id in rank_by_doc
                ]
                ndcgs.append(ndcg(clicked_ranks))
            mean_ndcg = sum(ndcgs) / len(ndcgs) if ndcgs else 0.0

        sample_top_ids: list[str] = []
        seen: set[str] = set()
        for search in query_searches:
            for doc_id in search.top_result_ids:
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                sample_top_ids.append(doc_id)
                if len(sample_top_ids) >= MAX_SAMPLE_TOP_IDS:
                    break
            if len(sample_top_ids) >= MAX_SAMPLE_TOP_IDS:
                break

        score = count * (1 + config.quality_weight * mean_ndcg)
        entries.append(
            TrendingEntry(
                query=query,
                count=count,
                score=score,
                ndcg=mean_ndcg,
                sample_top_ids=sample_top_ids,
            )
        )

    return sorted(entries, key=lambda entry: (-entry.score, entry.query))[
        : config.top_n
    ]
