import {
  backendEnabled,
  backendTrending,
  type TrendingResult,
} from "./backend";

export type { TrendingResult };

// Demo ledger before any real search-history exists. Frequency-only (mode
// "frequency"): counts, no quality signal — matching what Phase 1 serves.
const MOCK_TRENDING: TrendingResult = {
  entries: [
    { query: "wireless headphones", count: 41, score: 41, ndcg: 0 },
    { query: "carbon steel skillet", count: 33, score: 33, ndcg: 0 },
    { query: "minimalist desk lamp", count: 28, score: 28, ndcg: 0 },
    { query: "cozy reading corner", count: 22, score: 22, ndcg: 0 },
    { query: "something brass and warm", count: 19, score: 19, ndcg: 0 },
    { query: "gift for a coffee person", count: 14, score: 14, ndcg: 0 },
  ],
  mode: "frequency",
  stable_as_of: null,
  layer_perf: null,
};

// Demo mode always shows the mock ledger; a live backend either answers
// /search/trending or the surface hides entirely (no homepage empty state).
export async function getTrending(limit = 12): Promise<TrendingResult | null> {
  if (!backendEnabled()) {
    return { ...MOCK_TRENDING, entries: MOCK_TRENDING.entries.slice(0, limit) };
  }
  try {
    const result = await backendTrending(limit);
    return result.entries.length > 0 ? result : null;
  } catch {
    return null;
  }
}
