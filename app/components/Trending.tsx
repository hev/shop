import Link from "next/link";
import { getTrending } from "@/lib/trending";
import { searchHref, truncateQuery } from "@/lib/search-ui";
import { LayerPerfBadge } from "./LayerPerfBadge";
import { FeatureExplainer } from "./FeatureExplainer";

// "What everyone's searching" — queries aggregated by a Layer reduce UDF and
// ranked by volume (Phase 1) or volume × result quality (Phase 2). The
// aggregate counterpart to the header's personal "Your recent searches".
// Renders nothing when there's no trending data (no homepage empty state).
export async function Trending() {
  const result = await getTrending();
  if (!result || result.entries.length === 0) return null;

  // The explainer's live stat must not claim a quality signal Phase 1 isn't
  // computing — drive it off the mode the backend reports.
  const stat = result.mode === "quality" ? "by volume × result quality" : "by volume";

  return (
    <div className="mt-8">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-widest text-ink-500">
          Trending
        </span>
        <LayerPerfBadge perf={result.layer_perf} label="reduce UDF" />
        <FeatureExplainer id="trending" align="left" stat={stat} />
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {result.entries.slice(0, 8).map((entry) => (
          <Link
            key={entry.query}
            href={searchHref(entry.query)}
            title={`${entry.query} · ${entry.count.toLocaleString()} searches`}
            className="rounded-full border border-ink-200 bg-white px-3 py-1 text-xs text-ink-700 transition hover:border-ink-900 hover:text-ink-900"
          >
            {truncateQuery(entry.query)}
          </Link>
        ))}
      </div>
    </div>
  );
}
