import Link from "next/link";
import type { Product } from "@/lib/types";
import { ProductImage } from "./ProductImage";

export function ProductCard({ product, priority = false }: { product: Product; priority?: boolean }) {
  return (
    <Link
      href={`/product/${product.asin}`}
      className="group block"
    >
      <div className="relative aspect-square w-full overflow-hidden rounded-2xl bg-ink-100">
        <ProductImage
          product={product}
          fill
          sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 25vw"
          priority={priority}
          className="object-cover transition duration-500 group-hover:scale-105"
        />
        <div className="absolute left-3 top-3 rounded-full bg-white/90 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-ink-700">
          {product.category}
        </div>
      </div>

      <div className="mt-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-ink-900">
            {product.title}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-500">
            <Stars value={product.rating} />
            <span>{product.rating.toFixed(1)}</span>
            <span>·</span>
            <span>{formatCount(product.rating_count)}</span>
          </div>
          {product.tags && product.tags.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {product.tags.slice(0, 2).map((tag) => (
                <span
                  key={tag}
                  className="rounded-full bg-white px-2 py-0.5 text-[10px] font-medium text-ink-600 ring-1 ring-ink-200"
                >
                  {tag}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {product.price != null ? (
          <div className="shrink-0 text-sm font-semibold text-ink-900">
            ${product.price}
          </div>
        ) : null}
      </div>
    </Link>
  );
}

function Stars({ value }: { value: number }) {
  const full = Math.round(value);
  return (
    <span aria-label={`${value} out of 5`} className="text-accent">
      {"★".repeat(full)}
      <span className="text-ink-300">{"★".repeat(5 - full)}</span>
    </span>
  );
}

function formatCount(n: number) {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}
