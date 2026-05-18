import { NextResponse } from "next/server";
import { searchProducts } from "@/lib/search";
import { backendEnabled, backendSearch } from "@/lib/backend";
import { REVIEW_TAGS } from "@/lib/types";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const q = url.searchParams.get("q") ?? "";
  const limit = Number(url.searchParams.get("limit") ?? 24);
  const tags = url.searchParams
    .getAll("tag")
    .filter((tag) => (REVIEW_TAGS as readonly string[]).includes(tag));
  const t0 = performance.now();

  if (backendEnabled() && q.trim()) {
    try {
      const { products, layer_perf, stable_as_of } = await backendSearch(
        q,
        limit,
        tags,
      );
      return NextResponse.json({
        query: q,
        results: products,
        took_ms: Math.round(performance.now() - t0),
        source: "backend",
        layer_perf,
        stable_as_of,
      });
    } catch (err) {
      return NextResponse.json(
        {
          query: q,
          results: [],
          took_ms: Math.round(performance.now() - t0),
          source: "backend",
          error: err instanceof Error ? err.message : "search failed",
        },
        { status: 502 },
      );
    }
  }

  const results = searchProducts(q, limit, tags);
  return NextResponse.json({
    query: q,
    results,
    took_ms: Math.round(performance.now() - t0),
    source: "mock",
  });
}
