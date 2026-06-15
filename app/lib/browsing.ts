import type { Product } from "./types";
import type { ExpansionSummary, LayerPerf } from "./hevlayer-client";

// Client-side adapter for the "Similar to your browsing" rail. Posts the
// browsing-history ids to /api/browsing, which drives the hev layer TS client
// server-side. Type-only imports keep the server-only client out of the
// browser bundle.

export type BrowsingResult = {
  seeds: string[];
  results: Product[];
  expansion: ExpansionSummary | null;
  layer_perf: LayerPerf | null;
  source: string;
};

export async function fetchBrowsingSimilar(
  ids: string[],
  limit = 8,
): Promise<BrowsingResult> {
  const params = new URLSearchParams({
    ids: ids.join(","),
    limit: String(limit),
  });
  const res = await fetch(`/api/browsing?${params.toString()}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`browsing ${res.status}`);
  const json: unknown = await res.json();
  const obj = (json ?? {}) as Record<string, unknown>;
  return {
    seeds: Array.isArray(obj.seeds) ? (obj.seeds as string[]) : [],
    results: Array.isArray(obj.results) ? (obj.results as Product[]) : [],
    expansion: (obj.expansion as ExpansionSummary | null) ?? null,
    layer_perf: (obj.layer_perf as LayerPerf | null) ?? null,
    source: typeof obj.source === "string" ? obj.source : "gateway",
  };
}
