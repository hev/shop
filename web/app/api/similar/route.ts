import { NextResponse } from "next/server";
import { similarProducts } from "@/lib/search";
import { backendEnabled, backendSimilar, getCachedProduct } from "@/lib/backend";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const asin = url.searchParams.get("asin") ?? "";
  const limit = Number(url.searchParams.get("limit") ?? 6);
  const t0 = performance.now();

  if (backendEnabled()) {
    if (!getCachedProduct(asin)) {
      return NextResponse.json({
        asin,
        results: [],
        took_ms: Math.round(performance.now() - t0),
        source: "backend",
        note: "seed not in pod cache; visit /search first or add a fetch-by-id endpoint",
      });
    }
    try {
      const { products, layer_perf, stable_as_of } = await backendSimilar(
        asin,
        limit,
      );
      return NextResponse.json({
        asin,
        results: products,
        took_ms: Math.round(performance.now() - t0),
        source: "backend",
        layer_perf,
        stable_as_of,
      });
    } catch (err) {
      return NextResponse.json(
        {
          asin,
          results: [],
          took_ms: Math.round(performance.now() - t0),
          source: "backend",
          error: err instanceof Error ? err.message : "similar failed",
        },
        { status: 502 },
      );
    }
  }

  const results = similarProducts(asin, limit);
  return NextResponse.json({
    asin,
    results,
    took_ms: Math.round(performance.now() - t0),
    source: "mock",
  });
}
