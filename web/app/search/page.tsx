import Link from "next/link";
import { ProductGrid } from "@/components/ProductGrid";
import { searchProducts } from "@/lib/search";
import { backendEnabled, backendSearch } from "@/lib/backend";
import type { Product } from "@/lib/types";
import { REVIEW_TAGS } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; tag?: string | string[] }>;
}) {
  const { q = "", tag } = await searchParams;
  const selectedTags = (Array.isArray(tag) ? tag : tag ? [tag] : []).filter(
    (value): value is string => (REVIEW_TAGS as readonly string[]).includes(value),
  );
  const t0 = performance.now();
  let results: Product[] = [];
  let error: string | null = null;
  if (backendEnabled() && q.trim()) {
    try {
      results = await backendSearch(q, 48, selectedTags);
    } catch (e) {
      error = e instanceof Error ? e.message : "search failed";
    }
  } else {
    results = searchProducts(q, 48, selectedTags);
  }
  const took = Math.round(performance.now() - t0);

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
        <div className="text-xs text-ink-500">
          {results.length} {results.length === 1 ? "match" : "matches"} · {took}ms
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
        <ProductGrid products={results} priorityCount={4} />
      )}
    </div>
  );
}
