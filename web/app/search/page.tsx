import Link from "next/link";
import { ProductGrid } from "@/components/ProductGrid";
import { searchProducts } from "@/lib/search";
import {
  backendEnabled,
  backendSearch,
  type CountInfo,
  type LayerPerf,
} from "@/lib/backend";
import { LayerPerfBadge, StableAsOfBadge } from "@/components/LayerPerfBadge";
import type { Product } from "@/lib/types";
import { REVIEW_TAGS } from "@/lib/types";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 48;

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{
    q?: string;
    tag?: string | string[];
    cursor?: string;
  }>;
}) {
  const { q = "", tag, cursor } = await searchParams;
  const selectedTags = (Array.isArray(tag) ? tag : tag ? [tag] : []).filter(
    (value): value is string => (REVIEW_TAGS as readonly string[]).includes(value),
  );
  const t0 = performance.now();
  let results: Product[] = [];
  let layerPerf: LayerPerf | null = null;
  let stableAsOf: number | null = null;
  let nextCursor: string | null = null;
  let count: CountInfo | null = null;
  let error: string | null = null;
  if (backendEnabled() && q.trim()) {
    try {
      // Only ask for a count on page 1 — the count is query-scoped, not
      // page-scoped, so re-running it on every "load more" click is wasted
      // gateway work.
      const r = await backendSearch(q, {
        topK: PAGE_SIZE,
        tags: selectedTags,
        cursor: cursor || null,
        withCount: !cursor,
      });
      results = r.products;
      layerPerf = r.layer_perf;
      stableAsOf = r.stable_as_of;
      nextCursor = r.next_cursor;
      count = r.count;
    } catch (e) {
      error = e instanceof Error ? e.message : "search failed";
    }
  } else {
    results = searchProducts(q, PAGE_SIZE, selectedTags);
  }
  const took = Math.round(performance.now() - t0);

  const loadMoreHref = (() => {
    if (!nextCursor) return null;
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    for (const value of selectedTags) params.append("tag", value);
    params.set("cursor", nextCursor);
    return `/search?${params.toString()}`;
  })();

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <div className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest text-ink-500">
            Search
          </div>
          <h1 className="mt-1 font-display text-3xl tracking-tight">
            {q ? (
              <>
                Results for <span className="italic">"{q}"</span>
              </>
            ) : (
              "Everything in the catalog"
            )}
          </h1>
        </div>
        <div className="flex flex-col items-end gap-1.5 text-xs text-ink-500">
          <div>
            {results.length} {results.length === 1 ? "match" : "matches"} · {took}ms
            <span className="ml-1 text-ink-400">page</span>
          </div>
          {count ? (
            <div className="text-xs text-ink-500">
              {count.bounded ? "≥" : ""}
              <span className="font-mono text-ink-900">
                {count.count.toLocaleString()}
              </span>{" "}
              within cosine{" "}
              <span className="font-mono">{count.max_distance}</span>
            </div>
          ) : null}
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <LayerPerfBadge perf={layerPerf} label="query" />
            {count?.layer_perf ? (
              <LayerPerfBadge perf={count.layer_perf} label="count" />
            ) : null}
            <StableAsOfBadge stableAsOf={stableAsOf} />
          </div>
        </div>
      </div>

      <div className="mb-8 flex flex-wrap gap-2">
        {REVIEW_TAGS.map((reviewTag) => {
          const active = selectedTags.includes(reviewTag);
          const nextTags = active
            ? selectedTags.filter((value) => value !== reviewTag)
            : [...selectedTags, reviewTag];
          const params = new URLSearchParams();
          if (q) params.set("q", q);
          for (const value of nextTags) params.append("tag", value);
          return (
            <Link
              key={reviewTag}
              href={`/search?${params.toString()}`}
              className={`rounded-full px-3 py-1 text-xs font-medium ring-1 transition ${
                active
                  ? "bg-ink-900 text-white ring-ink-900"
                  : "bg-white text-ink-600 ring-ink-200 hover:text-ink-900"
              }`}
            >
              {reviewTag}
            </Link>
          );
        })}
      </div>

      {error ? (
        <div className="rounded-2xl border border-dashed border-red-300 bg-red-50 p-12 text-center">
          <p className="font-display text-2xl tracking-tight">Backend said no.</p>
          <p className="mt-2 font-mono text-xs text-red-900">{error}</p>
        </div>
      ) : results.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-ink-200 bg-white p-12 text-center">
          <p className="font-display text-2xl tracking-tight">k-nearest neighbors: ∅</p>
          <p className="mt-2 text-sm text-ink-500">
            No vectors crossed the similarity threshold. Try a different query, or{" "}
            <Link href="/" className="underline">
              go back and pick another vibe
            </Link>
            .
          </p>
        </div>
      ) : (
        <>
          <ProductGrid products={results} priorityCount={4} />
          {loadMoreHref ? (
            <div className="mt-10 flex justify-center">
              <Link
                href={loadMoreHref}
                className="rounded-full border border-ink-300 bg-white px-6 py-3 text-sm font-medium text-ink-900 transition hover:border-ink-900"
              >
                Load more — paginate via gateway cursor
              </Link>
            </div>
          ) : cursor ? (
            <p className="mt-10 text-center text-xs text-ink-500">
              End of results.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
