import { NextResponse } from "next/server";
import { HevlayerClient } from "@/lib/hevlayer-client";

export const runtime = "nodejs";

// One client per pod. The real hevlayer TypeScript client will carry the
// gateway base URL + key; the stand-in just needs the namespace.
const client = new HevlayerClient();

// GET /api/browsing?ids=A,B,C&limit=8 — "Similar to your browsing".
// `ids` is the shopper's recently-viewed history (from localStorage); we hand
// the whole array to the TS client's `searchById`, which unions the per-seed
// neighbor sets into one rail.
export async function GET(req: Request) {
  const url = new URL(req.url);
  const ids = (url.searchParams.get("ids") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const limit = Number(url.searchParams.get("limit") ?? 8);
  const t0 = performance.now();

  const { products, expansion } = await client.searchById(ids, { topK: limit });
  return NextResponse.json({
    seeds: expansion.seeds,
    results: products,
    expansion,
    took_ms: Math.round(performance.now() - t0),
    source: "mock",
    // Mock build makes no gateway call, so there is no round-trip to badge.
    // The gateway build surfaces per-seed query perf here.
    layer_perf: null,
  });
}
