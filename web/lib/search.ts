import { PRODUCTS } from "./mock-data";
import type { Product } from "./types";

function tokenize(s: string): string[] {
  return s
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length > 1);
}

function score(product: Product, tokens: string[]): number {
  if (tokens.length === 0) return 0;
  const hay = `${product.title} ${product.description} ${product.category}`.toLowerCase();
  let s = 0;
  for (const t of tokens) {
    if (product.title.toLowerCase().includes(t)) s += 4;
    if (product.category.toLowerCase() === t) s += 3;
    if (hay.includes(t)) s += 1;
  }
  s += Math.log10(product.rating_count + 1) * 0.4;
  s += (product.rating - 4) * 0.5;
  return s;
}

export function searchProducts(query: string, limit = 24, tags: string[] = []): Product[] {
  const tokens = tokenize(query);
  const products = tags.length
    ? PRODUCTS.filter((p) => p.tags?.some((tag) => tags.includes(tag)))
    : PRODUCTS;
  if (tokens.length === 0) {
    return [...products].sort((a, b) => b.rating_count - a.rating_count).slice(0, limit);
  }
  return products.map((p) => ({ p, s: score(p, tokens) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, limit)
    .map((x) => x.p);
}

export function similarProducts(asin: string, limit = 6): Product[] {
  const seed = PRODUCTS.find((p) => p.asin === asin);
  if (!seed) return [];
  const seedTokens = tokenize(seed.title);
  return PRODUCTS.filter((p) => p.asin !== asin)
    .map((p) => {
      let s = 0;
      if (p.category === seed.category) s += 5;
      const hay = `${p.title} ${p.description}`.toLowerCase();
      for (const t of seedTokens) if (hay.includes(t)) s += 1;
      if (p.price != null && seed.price != null) {
        const priceRatio =
          Math.min(p.price, seed.price) / Math.max(p.price, seed.price);
        s += priceRatio * 1.5;
      }
      return { p, s };
    })
    .sort((a, b) => b.s - a.s)
    .slice(0, limit)
    .map((x) => x.p);
}
