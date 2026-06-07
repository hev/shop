import Link from "next/link";
import { getRecentSearches } from "@/lib/recent-searches";
import { LayerPerfBadge } from "./LayerPerfBadge";

function truncate(q: string, max = 40): string {
  return q.length > max ? q.slice(0, max - 1).trimEnd() + "…" : q;
}

// "What people are asking the index" — recent distinct queries read back
// from Layer search-history. Renders nothing when the history is empty or
// the endpoint is unavailable.
export async function RecentSearches() {
  const result = await getRecentSearches();
  if (!result || result.queries.length === 0) return null;

  return (
    <div className="mt-8">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-widest text-ink-500">
          Recent searches
        </span>
        <LayerPerfBadge perf={result.layer_perf} label="search-history" />
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {result.queries.slice(0, 8).map((query) => (
          <Link
            key={query}
            href={`/search?q=${encodeURIComponent(query)}`}
            title={query}
            className="rounded-full border border-ink-200 bg-white px-3 py-1 text-xs text-ink-700 transition hover:border-ink-900 hover:text-ink-900"
          >
            {truncate(query)}
          </Link>
        ))}
      </div>
    </div>
  );
}
