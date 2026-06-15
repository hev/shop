import { NextResponse } from "next/server";
import { HevlayerClient, browsingClientEnabled } from "@/lib/hevlayer-client";

export const runtime = "nodejs";

// One client per pod. It reads LAYER_GATEWAY_URL / LAYER_GATEWAY_API_KEY /
// LAYER_PRODUCT_NAMESPACE from the environment (the prod web pod holds these;
// locally they live in .env.local).
const client = new HevlayerClient();

// GET /api/browsing?ids=A,B,C&limit=8 — "Similar to your browsing".
// `ids` is the shopper's recently-viewed history (from localStorage); we hand
// the whole array to the TS client's `searchById`, which runs one multi-query
// round trip (one nearest-neighbor leg per seed) and fuses the rankings (RRF).
export async function GET(req: Request) {
  const url = new URL(req.url);
  const ids = (url.searchParams.get("ids") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const limit = Number(url.searchParams.get("limit") ?? 8);
  const t0 = performance.now();

  try {
    const { products, expansion, layer_perf } = await client.searchById(ids, {
      topK: limit,
    });
    return NextResponse.json({
      seeds: expansion.seeds,
      results: products,
      expansion,
      took_ms: Math.round(performance.now() - t0),
      source: browsingClientEnabled() ? "gateway" : "disabled",
      layer_perf,
    });
  } catch (err) {
    // The rail degrades to invisible on failure (e.g. a stale viewed ASIN whose
    // vector no longer resolves → the gateway 404s the whole batch). Log the
    // detail server-side; never thread upstream error bytes into the response.
    console.error("[browsing] searchById failed:", err);
    return NextResponse.json({
      seeds: [],
      results: [],
      expansion: null,
      took_ms: Math.round(performance.now() - t0),
      source: "gateway",
      layer_perf: null,
    });
  }
}
