"use client";

import { useEffect } from "react";
import { recordView, type ViewedProduct } from "@/lib/recently-viewed";

// Mounted on the product page. Records the current product into the
// localStorage browsing history that seeds the homepage "Similar to your
// browsing" rail. Renders nothing.
export function RecordView({ product }: { product: ViewedProduct }) {
  const { asin, title, image_url, image_blob, category } = product;
  useEffect(() => {
    recordView({ asin, title, image_url, image_blob, category });
  }, [asin, title, image_url, image_blob, category]);
  return null;
}
