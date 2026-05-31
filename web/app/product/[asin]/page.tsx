import { notFound } from "next/navigation";
import Link from "next/link";
import { findByAsin, MOCK_REVIEW_TEXT, PRODUCTS } from "@/lib/mock-data";
import { similarProducts } from "@/lib/search";
import {
  backendEnabled,
  backendProduct,
  backendReviewSamples,
  backendReviewSearch,
  backendSimilar,
  type CountInfo,
  type LayerPerf,
} from "@/lib/backend";
import { ProductGrid } from "@/components/ProductGrid";
import { ProductImage } from "@/components/ProductImage";
import { LayerPerfBadge, StableAsOfBadge } from "@/components/LayerPerfBadge";
import type { Product, ReviewHit, ReviewSample } from "@/lib/types";

export const dynamic = "force-dynamic";

export function generateStaticParams() {
  if (backendEnabled()) return [];
  return PRODUCTS.map((p) => ({ asin: p.asin }));
}

type LoadedPage = {
  product: Product;
  similar: Product[];
  reviews: ReviewHit[];
  samples: ReviewSample[];
  perf: {
    fetchDocument: LayerPerf | null;     // /v2/namespaces/.../documents/{asin}
    similarQuery: LayerPerf | null;      // /recommend nearest_to_id query
    reviewQuery: LayerPerf | null;       // /v2/namespaces/.../query (review)
    reviewStableAsOf: number | null;
    reviewCount: CountInfo | null;       // /v2/namespaces/.../result-count fan-out
  };
};

async function load(asin: string, reviewQuery: string): Promise<LoadedPage | null> {
  if (backendEnabled()) {
    const fetched = await backendProduct(asin).catch(() => null);
    if (!fetched) return null;
    const { product, layer_perf: fetchDocumentPerf } = fetched;
    const sampleIds = Object.values(product.tag_samples ?? {}).flat();
    const [similarRes, reviewRes, samples] = await Promise.all([
      backendSimilar(asin, 8).catch(() => ({
        products: [] as Product[],
        layer_perf: null,
        stable_as_of: null,
      })),
      backendReviewSearch(asin, reviewQuery || product.title, {
        topK: 8,
        withCount: true,
      }).catch(() => ({
        reviews: [] as ReviewHit[],
        layer_perf: null,
        stable_as_of: null,
        next_cursor: null,
        count: null,
      })),
      backendReviewSamples(asin, sampleIds).catch(() => [] as ReviewSample[]),
    ]);
    return {
      product,
      similar: similarRes.products,
      reviews: reviewRes.reviews,
      samples,
      perf: {
        fetchDocument: fetchDocumentPerf,
        similarQuery: similarRes.layer_perf,
        reviewQuery: reviewRes.layer_perf,
        reviewStableAsOf: reviewRes.stable_as_of,
        reviewCount: reviewRes.count,
      },
    };
  }
  const product = findByAsin(asin);
  if (!product) return null;
  const samples = Object.values(product.tag_samples ?? {})
    .flat()
    .map((review_id) => ({
      review_id,
      asin,
      title: null,
      text: MOCK_REVIEW_TEXT[review_id] ?? "",
      rating: null,
    }))
    .filter((sample) => sample.text);
  const reviews = samples.slice(0, 4).map((sample, index) => ({
    id: `${sample.review_id}:chunk:0000`,
    dist: null,
    review_id: sample.review_id,
    asin,
    chunk_idx: index,
    text_chunk: sample.text,
    rating: sample.rating,
    title: sample.title ?? "",
    helpful_vote: 0,
  }));
  return {
    product,
    similar: similarProducts(asin, 8),
    reviews,
    samples,
    perf: {
      fetchDocument: null,
      similarQuery: null,
      reviewQuery: null,
      reviewStableAsOf: null,
      reviewCount: null,
    },
  };
}

export default async function ProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ asin: string }>;
  searchParams: Promise<{ rq?: string }>;
}) {
  const { asin } = await params;
  const { rq = "" } = await searchParams;
  const data = await load(asin, rq);
  if (!data) notFound();
  const { product, similar, reviews, samples, perf } = data;
  const sampleById = new Map(samples.map((sample) => [sample.review_id, sample]));

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <nav className="mb-6 text-xs text-ink-500">
        <Link href="/" className="hover:text-ink-900">
          hev·shop
        </Link>
        <span className="mx-2">/</span>
        <Link
          href={`/search?q=${encodeURIComponent(product.category.toLowerCase())}`}
          className="hover:text-ink-900"
        >
          {product.category || "results"}
        </Link>
        <span className="mx-2">/</span>
        <span className="text-ink-700">{product.title}</span>
      </nav>

      <div className="grid grid-cols-1 gap-10 lg:grid-cols-2">
        <div className="relative aspect-square w-full overflow-hidden rounded-3xl bg-ink-100">
          <ProductImage
            product={product}
            fill
            sizes="(max-width: 1024px) 100vw, 50vw"
            priority
            className="object-cover"
          />
        </div>

        <div className="flex flex-col">
          {product.category ? (
            <div className="text-xs font-semibold uppercase tracking-widest text-accent">
              {product.category}
            </div>
          ) : null}
          <h1 className="mt-2 font-display text-4xl leading-tight tracking-tight text-ink-900">
            {product.title}
          </h1>

          {product.rating_count > 0 ? (
            <div className="mt-3 flex items-center gap-2 text-sm text-ink-500">
              <span className="text-accent">
                {"★".repeat(Math.max(0, Math.round(product.rating)))}
              </span>
              <span>{product.rating.toFixed(1)}</span>
              <span>·</span>
              <span>{product.rating_count.toLocaleString()} reviews</span>
            </div>
          ) : null}

          {product.tags && product.tags.length > 0 ? (
            <div className="mt-5 flex flex-wrap gap-2">
              {product.tags.map((tag) => {
                const count = product.tag_counts?.[tag] ?? 0;
                const sampleText = (product.tag_samples?.[tag] ?? [])
                  .map((id) => sampleById.get(id)?.text)
                  .filter(Boolean)
                  .join("\n\n");
                return (
                  <span
                    key={tag}
                    title={sampleText || undefined}
                    className="rounded-full bg-white px-3 py-1 text-xs font-medium text-ink-700 ring-1 ring-ink-200"
                  >
                    {tag}
                    {count > 0 ? (
                      <span className="ml-1 text-ink-400">{count}</span>
                    ) : null}
                  </span>
                );
              })}
            </div>
          ) : null}

          {product.price != null ? (
            <div className="mt-6 font-display text-3xl text-ink-900">
              ${product.price}
            </div>
          ) : null}

          {product.description ? (
            <p className="mt-6 max-w-prose leading-relaxed text-ink-700">
              {product.description}
            </p>
          ) : null}

          <div className="mt-8 flex gap-3">
            <button
              type="button"
              className="flex-1 rounded-full bg-ink-900 px-6 py-3.5 text-sm font-medium text-white transition hover:bg-ink-700 sm:flex-none"
            >
              {product.price != null
                ? `UPSERT into cart — $${product.price}`
                : "UPSERT into cart"}
            </button>
            <button
              type="button"
              aria-label="Save"
              className="rounded-full border border-ink-300 p-3.5 text-ink-700 transition hover:border-ink-900 hover:text-ink-900"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-4 w-4"
              >
                <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
              </svg>
            </button>
          </div>

          <dl className="mt-10 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-3 border-t border-ink-200 pt-6 text-sm">
            <dt className="text-ink-500">ASIN</dt>
            <dd className="font-mono text-ink-900">{product.asin}</dd>
            <dt className="text-ink-500">Embedding</dt>
            <dd className="font-mono text-ink-900">CLIP ViT-L/14 · 768d</dd>
            <dt className="text-ink-500">Distance metric</dt>
            <dd className="font-mono text-ink-900">cosine</dd>
            <dt className="text-ink-500">Doc fetch</dt>
            <dd className="flex flex-wrap items-center gap-1.5">
              {perf.fetchDocument ? (
                <LayerPerfBadge perf={perf.fetchDocument} />
              ) : (
                <span className="font-mono text-xs text-ink-400">
                  (mock data — backend off)
                </span>
              )}
              <span className="font-mono text-xs text-ink-400">
                GET /v2/namespaces/amazon-products/documents/{product.asin}
              </span>
            </dd>
            <dt className="text-ink-500">Similar query</dt>
            <dd className="flex flex-wrap items-center gap-1.5">
              {perf.similarQuery ? (
                <LayerPerfBadge perf={perf.similarQuery} />
              ) : (
                <span className="font-mono text-xs text-ink-400">—</span>
              )}
              <span className="font-mono text-xs text-ink-400">
                nearest_to_id → /query
              </span>
            </dd>
          </dl>

          <p className="mt-4 text-xs text-ink-500">
            <span className="font-semibold text-ink-700">Doc fetch</span> goes
            through Layer's Aerospike pull-through cache; <span className="font-mono">cache hit</span>{" "}
            served the row without touching turbopuffer. The <span className="font-semibold text-ink-700">similar query</span>{" "}
            asks Layer for nearest neighbors of the stored product vector — queries
            don't go through the doc cache, so no cache header is set.
          </p>
        </div>
      </div>

      <section className="mt-20 border-t border-ink-200 pt-10">
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-widest text-ink-500">
              Reviews
            </div>
            <h2 className="mt-1 font-display text-3xl tracking-tight">
              Search inside customer reviews
            </h2>
            {perf.reviewCount ? (
              <p className="mt-2 text-sm text-ink-500">
                {perf.reviewCount.bounded ? "≥" : ""}
                <span className="font-mono text-ink-900">
                  {perf.reviewCount.count.toLocaleString()}
                </span>{" "}
                review chunks within cosine{" "}
                <span className="font-mono">{perf.reviewCount.max_distance}</span>{" "}
                of the query
              </p>
            ) : null}
            {(perf.reviewQuery || perf.reviewStableAsOf !== null) && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <LayerPerfBadge perf={perf.reviewQuery} label="review query" />
                {perf.reviewCount?.layer_perf ? (
                  <LayerPerfBadge
                    perf={perf.reviewCount.layer_perf}
                    label="review count"
                  />
                ) : null}
                <StableAsOfBadge stableAsOf={perf.reviewStableAsOf} />
              </div>
            )}
          </div>
          <form className="flex w-full gap-2 sm:w-auto" action={`/product/${product.asin}`}>
            <input
              name="rq"
              defaultValue={rq}
              placeholder="battery, fit, setup"
              className="min-w-0 flex-1 rounded-full border border-ink-200 bg-white px-4 py-2 text-sm outline-none transition focus:border-ink-900 sm:w-72"
            />
            <button
              type="submit"
              className="rounded-full bg-ink-900 px-4 py-2 text-sm font-medium text-white"
            >
              Search
            </button>
          </form>
        </div>

        {reviews.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2">
            {reviews.map((review) => (
              <article
                key={review.id}
                className="rounded-2xl bg-white p-5 ring-1 ring-ink-200"
              >
                <div className="mb-3 flex items-center justify-between gap-3 text-xs text-ink-500">
                  <span className="font-mono">{review.review_id}</span>
                  {review.rating != null ? (
                    <span className="text-accent">
                      {"★".repeat(Math.max(0, Math.round(review.rating)))}
                    </span>
                  ) : null}
                </div>
                <p className="text-sm leading-6 text-ink-700">{review.text_chunk}</p>
              </article>
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-ink-200 bg-white p-8 text-sm text-ink-500">
            No review chunks are indexed for this product yet.
          </div>
        )}
      </section>

      {/* Similar products */}
      {similar.length > 0 && (
        <section className="mt-24">
          <div className="mb-8 flex items-end justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-widest text-ink-500">
                Visually similar
              </div>
              <h2 className="mt-1 font-display text-3xl tracking-tight">
                You might also like
              </h2>
            </div>
            <span className="hidden text-xs text-ink-500 sm:inline">
              via CLIP image embeddings
            </span>
          </div>
          <ProductGrid products={similar} />
        </section>
      )}
    </div>
  );
}
