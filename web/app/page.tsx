import Link from "next/link";
import { ProductGrid } from "@/components/ProductGrid";
import { ProductImage } from "@/components/ProductImage";
import { LayerPerfBadge } from "@/components/LayerPerfBadge";
import { DropBand } from "@/components/DropBand";
import { RecentSearches } from "@/components/RecentSearches";
import { PRODUCTS } from "@/lib/mock-data";
import {
  backendEnabled,
  backendMeta,
  backendSearch,
  type BackendMeta,
  type CategoryBucket,
} from "@/lib/backend";
import { warmOnce } from "@/lib/layer";
import type { Product } from "@/lib/types";

const FALLBACK_CATEGORIES: CategoryBucket[] = [
  { value: "Kitchen", doc_count: 0 },
  { value: "Home", doc_count: 0 },
  { value: "Apparel", doc_count: 0 },
  { value: "Electronics", doc_count: 0 },
  { value: "Books", doc_count: 0 },
];
const FEATURED_QUERIES = [
  "wireless headphones",
  "minimalist desk lamp",
  "carbon steel skillet",
];

export const dynamic = "force-dynamic";

function fallbackFeatured(): Product[] {
  return [...PRODUCTS].sort((a, b) => b.rating - a.rating).slice(0, 12);
}

async function getFeatured(): Promise<Product[]> {
  if (!backendEnabled()) {
    return fallbackFeatured();
  }
  const batches = await Promise.allSettled(
    FEATURED_QUERIES.map((q) => backendSearch(q, { topK: 6 })),
  );
  const seen = new Set<string>();
  const out: Product[] = [];
  for (const b of batches) {
    if (b.status !== "fulfilled") continue;
    for (const p of b.value.products) {
      if (seen.has(p.asin)) continue;
      seen.add(p.asin);
      out.push(p);
      if (out.length >= 12) return out;
    }
  }
  return out.length > 0 ? out : fallbackFeatured();
}

async function getMeta(): Promise<BackendMeta | null> {
  if (!backendEnabled()) return null;
  try {
    return await backendMeta();
  } catch {
    return null;
  }
}

function formatStableAsOf(epochMs: number): string {
  return new Date(epochMs).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export default async function HomePage() {
  warmOnce();
  const [featured, meta] = await Promise.all([getFeatured(), getMeta()]);
  const hero = featured.slice(0, 3);
  const categories = meta?.categories.length
    ? meta.categories
    : FALLBACK_CATEGORIES;
  const vectorCount = meta?.vectors ?? PRODUCTS.length;
  const lastIndexedAt = meta?.stable_as_of ?? null;

  return (
    <div>
      {/* Hero */}
      <section className="border-b border-ink-200 bg-white">
        <div className="mx-auto grid max-w-7xl grid-cols-1 gap-10 px-4 py-16 lg:grid-cols-2 lg:py-24">
          <div className="flex flex-col justify-center">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="text-xs font-semibold uppercase tracking-widest text-accent">
                {vectorCount.toLocaleString()} vectors indexed
                {lastIndexedAt !== null
                  ? ` · last indexed at ${formatStableAsOf(lastIndexedAt)}`
                  : null}
              </span>
              <LayerPerfBadge perf={meta?.layer_perf ?? null} label="/meta" />
            </div>
            <h1 className="mt-4 font-display text-5xl leading-[1.05] tracking-tight text-ink-900 sm:text-6xl">
              Find things by how they look, not what we called them.
            </h1>
            <p className="mt-6 max-w-md text-base text-ink-700">
              hev·shop is a storefront wrapped around a vector database. Every
              product is a 768-dimensional CLIP embedding. Type a vibe —
              "cozy reading corner", "something brass and warm" — and we'll
              return the nearest neighbors. Spelling and grammar entirely optional.
            </p>
            <div className="mt-8 flex gap-3">
              <Link
                href="/search?q=wireless+headphones"
                className="rounded-full bg-ink-900 px-5 py-3 text-sm font-medium text-white transition hover:bg-ink-700"
              >
                Run a query
              </Link>
              <Link
                href="/search?q=brass+and+warm"
                className="rounded-full border border-ink-300 px-5 py-3 text-sm font-medium text-ink-900 transition hover:border-ink-900"
              >
                Try "brass and warm"
              </Link>
            </div>
            <RecentSearches />
          </div>

          <div className="grid grid-cols-3 gap-3">
            {hero.map((p, i) => (
              <Link
                key={p.asin}
                href={`/product/${p.asin}`}
                className={`relative overflow-hidden rounded-2xl bg-ink-100 ${
                  i === 0 ? "col-span-2 row-span-2 aspect-square" : "aspect-square"
                }`}
              >
                <ProductImage
                  product={p}
                  fill
                  sizes="(max-width: 1024px) 50vw, 33vw"
                  priority
                  className="object-cover transition duration-700 hover:scale-105"
                />
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Daily drop */}
      <DropBand />

      {/* Categories */}
      <section className="mx-auto max-w-7xl px-4 py-12">
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-3 text-xs font-semibold uppercase tracking-widest text-ink-500">
            filter
          </span>
          {categories.map((c) => (
            <Link
              key={c.value}
              href={`/search?q=${encodeURIComponent(c.value.toLowerCase())}`}
              className="rounded-full border border-ink-200 bg-white px-4 py-1.5 text-sm transition hover:border-ink-900"
            >
              {c.value}
              {c.doc_count > 0 ? (
                <span className="ml-2 text-xs text-ink-500">
                  {c.doc_count.toLocaleString()}
                </span>
              ) : null}
            </Link>
          ))}
        </div>
      </section>

      {/* Featured grid */}
      <section className="mx-auto max-w-7xl px-4 pb-16">
        <div className="mb-8 flex items-end justify-between">
          <div>
            <h2 className="font-display text-3xl tracking-tight">
              Browse the index
            </h2>
            <p className="mt-1 text-sm text-ink-500">
              {categories.length === 1
                ? `${categories[0].value.toLowerCase()} — more categories coming online soon.`
                : `${categories.length} categories indexed and growing.`}
            </p>
          </div>
          <Link
            href={`/search?q=${encodeURIComponent(
              (categories[0]?.value ?? "").toLowerCase(),
            )}`}
            className="hidden text-sm font-medium text-ink-700 hover:text-ink-900 sm:inline"
          >
            SELECT * →
          </Link>
        </div>
        <div className="mb-6 flex flex-wrap gap-2">
          {categories.map((c) => (
            <Link
              key={c.value}
              href={`/search?q=${encodeURIComponent(c.value.toLowerCase())}`}
              className="rounded-full border border-ink-200 bg-white px-4 py-1.5 text-sm transition hover:border-ink-900"
            >
              {c.value}
              {c.doc_count > 0 ? (
                <span className="ml-2 text-xs text-ink-500">
                  {c.doc_count.toLocaleString()}
                </span>
              ) : null}
            </Link>
          ))}
        </div>
        <ProductGrid products={featured} priorityCount={4} />
      </section>
    </div>
  );
}
