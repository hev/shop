"use client";

import { useCallback, useEffect, useState } from "react";
import { ProductGrid } from "./ProductGrid";
import { FeatureExplainer } from "./FeatureExplainer";
import { fetchBrowsingSimilar } from "@/lib/browsing";
import {
  getRecentlyViewed,
  RECENTLY_VIEWED_EVENT,
  type ViewedProduct,
} from "@/lib/recently-viewed";
import type { Product } from "@/lib/types";
import type { ExpansionSummary } from "@/lib/hevlayer-client";

// Need at least two viewed products for a *union* to mean anything — a single
// seed is just the product page's "Visually similar" rail. Cap the seeds we
// send so the rail stays a session-taste signal, not the whole history.
const MIN_SEEDS = 2;
const MAX_SEEDS = 6;

// "Similar to your browsing" — seeded by the localStorage history, served by
// the hev layer TS client's `searchById` (multi-query + RRF over the products
// you viewed). Client component because the history lives in the browser.
// Follows the storefront rule that personalized surfaces degrade to
// *invisible*: renders nothing until there are enough seeds and a result.
export function BrowsingRail() {
  const [viewed, setViewed] = useState<ViewedProduct[]>([]);
  const [results, setResults] = useState<Product[]>([]);
  const [expansion, setExpansion] = useState<ExpansionSummary | null>(null);

  const refresh = useCallback(async () => {
    const recent = getRecentlyViewed();
    setViewed(recent);
    const ids = recent.slice(0, MAX_SEEDS).map((v) => v.asin);
    if (ids.length < MIN_SEEDS) {
      setResults([]);
      setExpansion(null);
      return;
    }
    try {
      const res = await fetchBrowsingSimilar(ids, 8);
      setResults(res.results);
      setExpansion(res.expansion);
    } catch {
      setResults([]);
      setExpansion(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onChange = () => void refresh();
    window.addEventListener(RECENTLY_VIEWED_EVENT, onChange);
    window.addEventListener("focus", onChange);
    return () => {
      window.removeEventListener(RECENTLY_VIEWED_EVENT, onChange);
      window.removeEventListener("focus", onChange);
    };
  }, [refresh]);

  if (viewed.length < MIN_SEEDS || results.length === 0) return null;

  return (
    <section className="mx-auto max-w-7xl px-4 py-12">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest text-ink-500">
            Similar to your browsing
          </div>
          <h2 className="mt-1 font-display text-3xl tracking-tight">
            Inspired by your browsing
          </h2>
        </div>
        <FeatureExplainer
          id="browsing-rail"
          stat={
            expansion
              ? `${expansion.legs} queries → RRF → ${expansion.fused} results · TS client (mock)`
              : undefined
          }
        />
      </div>
      <ProductGrid products={results} />
    </section>
  );
}
