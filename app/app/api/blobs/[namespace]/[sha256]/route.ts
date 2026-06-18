import { NextResponse } from "next/server";

const GATEWAY_URL = process.env.LAYER_GATEWAY_URL ?? "";
const GATEWAY_API_KEY = (process.env.LAYER_GATEWAY_API_KEY ?? "").trim();
const SHA256_RE = /^[0-9a-fA-F]{64}$/;

export const runtime = "nodejs";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ namespace: string; sha256: string }> },
) {
  const { namespace, sha256 } = await params;
  if (!GATEWAY_URL || !GATEWAY_API_KEY || !SHA256_RE.test(sha256)) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  const url = `${GATEWAY_URL.replace(/\/$/, "")}/v1/namespaces/${encodeURIComponent(
    namespace,
  )}/blobs/${sha256.toLowerCase()}`;
  const upstream = await fetch(url, {
    headers: { Authorization: `Bearer ${GATEWAY_API_KEY}` },
    cache: "force-cache",
  }).catch(() => null);

  if (!upstream || !upstream.ok || !upstream.body) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/octet-stream",
      "cache-control":
        upstream.headers.get("cache-control") ??
        "public, max-age=31536000, immutable",
      etag: upstream.headers.get("etag") ?? `"${sha256.toLowerCase()}"`,
    },
  });
}
