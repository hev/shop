import type { Product } from "./types";

// Client-side browsing history: the array of product IDs we feed to the hev
// layer TS client's `searchById` to build the "Similar to your browsing" rail.
// Lives in localStorage (no server round-trip, no account) and is read back by
// `BrowsingRail`. Browser-only — every accessor guards `window` so it is inert
// during SSR.

const STORAGE_KEY = "hev-shop:recently-viewed";
const MAX_VIEWED = 12;

// Fired on the window whenever the history changes so a mounted rail can
// refresh without a full navigation (e.g. you opened a product in this tab and
// came back).
export const RECENTLY_VIEWED_EVENT = "hev-shop:recently-viewed-changed";

// We only persist what a card needs to render plus the ASIN we send upstream —
// not the full ProductRecord. The rail sends ids; the gateway (or, here, the
// mock catalog) re-hydrates the neighbors.
export type ViewedProduct = Pick<
  Product,
  "asin" | "title" | "image_url" | "category"
>;

function read(): ViewedProduct[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (v): v is ViewedProduct =>
        !!v && typeof (v as ViewedProduct).asin === "string",
    );
  } catch {
    return [];
  }
}

function write(items: ViewedProduct[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    window.dispatchEvent(new Event(RECENTLY_VIEWED_EVENT));
  } catch {
    // private mode / quota exceeded — history is best-effort, drop silently.
  }
}

// Move `product` to the front (newest first), dedupe by ASIN, cap the list.
export function recordView(product: ViewedProduct): void {
  const existing = read().filter((v) => v.asin !== product.asin);
  const next = [
    {
      asin: product.asin,
      title: product.title,
      image_url: product.image_url,
      category: product.category,
    },
    ...existing,
  ].slice(0, MAX_VIEWED);
  write(next);
}

export function getRecentlyViewed(): ViewedProduct[] {
  return read();
}

export function getRecentlyViewedIds(limit = MAX_VIEWED): string[] {
  return read()
    .slice(0, limit)
    .map((v) => v.asin);
}
