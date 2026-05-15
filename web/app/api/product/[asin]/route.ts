import { NextResponse } from "next/server";
import { findByAsin } from "@/lib/mock-data";
import { backendEnabled, backendProduct } from "@/lib/backend";

export const runtime = "nodejs";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ asin: string }> },
) {
  const { asin } = await params;

  if (backendEnabled()) {
    const product = await backendProduct(asin).catch(() => null);
    if (product) {
      return NextResponse.json({ product, source: "backend" });
    }
    return NextResponse.json(
      { product: null, source: "backend" },
      { status: 404 },
    );
  }

  const product = findByAsin(asin);
  if (!product) {
    return NextResponse.json({ product: null, source: "mock" }, { status: 404 });
  }
  return NextResponse.json({ product, source: "mock" });
}
