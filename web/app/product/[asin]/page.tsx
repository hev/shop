import { notFound } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import { findByAsin, MOCK_REVIEW_TEXT, PRODUCTS } from "@/lib/mock-data";
import { similarProducts } from "@/lib/search";
import {
  backendEnabled,
  backendProduct,
  backendReviewSamples,
  backendReviewSearch,
  backendSimilar,
} from "@/lib/backend";
import { ProductGrid } from "@/components/ProductGrid";
import type { Product, ReviewHit, ReviewSample } from "@/lib/types";

export const dynamic = "force-dynamic";

export function generateStaticParams() {
  if (backendEnabled()) return [];
  return PRODUCTS.map((p) => ({ asin: p.asin }));
}

async function load(
  asin: string,
  reviewQuery: string,
): Promise<{
  product: Product;
  similar: Product[];
  reviews: ReviewHit[];
  samples: ReviewSample[];
} | null> {
  if (backendEnabled()) {
    const product = await backendProduct(asin).catch(() => null);
    if (!product) return null;
    const similar = await backendSimilar(asin, 8).catch(() => [] as Product[]);
    const sampleIds = Object.values(product.tag_samples ?? {}).flat();
    const [reviews, samples] = await Promise.all([
      backendReviewSearch(asin, reviewQuery || product.title, 8).catch(
        () => [] as ReviewHit[],
      ),
      backendReviewSamples(asin, sampleIds).catch(() => [] as ReviewSample[]),
    ]);
    return { product, similar, reviews, samples };
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
  return { product, similar: similarProducts(asin, 8), reviews, samples };
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
  const { product, similar, reviews, samples } = data;
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
          {product.image_url ? (
            <Image
              src={product.image_url}
              alt={product.title}
              fill
              sizes="(max-width: 1024px) 100vw, 50vw"
              priority
              className="object-cover"
            />
          ) : null}
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

          <dl className="mt-10 grid grid-cols-2 gap-y-4 border-t border-ink-200 pt-6 text-sm">
            <dt className="text-ink-500">ASIN</dt>
            <dd className="font-mono text-ink-900">{product.asin}</dd>
            <dt className="text-ink-500">Embedding</dt>
            <dd className="font-mono text-ink-900">CLIP ViT-L/14 · 768d</dd>
            <dt className="text-ink-500">Distance metric</dt>
            <dd className="font-mono text-ink-900">cosine</dd>
            <dt className="text-ink-500">Returns policy</dt>
            <dd className="text-ink-900">we keep the vector either way</dd>
          </dl>
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
