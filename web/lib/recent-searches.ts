import {
  backendEnabled,
  backendRecentSearches,
  type RecentSearchesResult,
} from "./backend";

export type { RecentSearchesResult };

// What the demo ledger of queries looks like before anyone has searched.
// Matches the storefront's register and mostly lands hits in the mock catalog.
const MOCK_QUERIES = [
  "cozy reading corner",
  "wireless headphones",
  "something brass and warm",
  "carbon steel skillet",
  "minimalist desk lamp",
  "brutalist but soft",
  "gift for a coffee person",
  "blck hedphones",
];

// Demo mode always shows the mock ledger; a live backend either answers
// /search/recent or the surface hides entirely.
export async function getRecentSearches(
  limit = 8,
): Promise<RecentSearchesResult | null> {
  if (!backendEnabled()) {
    return { queries: MOCK_QUERIES.slice(0, limit), layer_perf: null };
  }
  try {
    const result = await backendRecentSearches(limit);
    return result.queries.length > 0 ? result : null;
  } catch {
    return null;
  }
}
