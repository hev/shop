import { NextResponse } from "next/server";
import { searchProducts } from "@/lib/search";
import { backendEnabled, backendSearch } from "@/lib/backend";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const q = url.searchParams.get("q") ?? "";
  const limit = Number(url.searchParams.get("limit") ?? 24);
  const t0 = performance.now();

  const cursor = url.searchParams.get("cursor") || undefined;
  const withCount = url.searchParams.get("with_count") === "true";
  if (backendEnabled() && q.trim()) {
    try {
      const {
        products,
        layer_perf,
        stable_as_of,
        next_cursor,
        count,
      } = await backendSearch(q, { topK: limit, cursor, withCount });
      return NextResponse.json({
        query: q,
        results: products,
        took_ms: Math.round(performance.now() - t0),
        source: "backend",
        layer_perf,
        stable_as_of,
        next_cursor,
        count,
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

  const results = searchProducts(q, limit);
  return NextResponse.json({
    query: q,
    results,
    took_ms: Math.round(performance.now() - t0),
    source: "mock",
  });
}
