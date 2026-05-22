"use client";

import Image from "next/image";
import { useState } from "react";
import type { Product } from "@/lib/types";

type Props = {
  product: Product;
  alt?: string;
  className?: string;
  sizes?: string;
  priority?: boolean;
  fill?: boolean;
  width?: number;
  height?: number;
};

// Wraps next/image with a one-step fallback from the storefront image proxy
// (image_src → /product/{asin}/image → gateway blob route) back to the
// Amazon CDN URL on image_url. The blob route 404s cleanly while the
// backfill is still draining; this keeps thumbnails rendering through it.
export function ProductImage({
  product,
  alt,
  className,
  sizes,
  priority,
  fill,
  width,
  height,
}: Props) {
  const primary = product.image_src ?? product.image_url;
  const [src, setSrc] = useState(primary);

  if (!primary) return null;

  return (
    <Image
      src={src}
      alt={alt ?? product.title}
      fill={fill}
      width={fill ? undefined : width}
      height={fill ? undefined : height}
      sizes={sizes}
      priority={priority}
      className={className}
      onError={() => {
        if (product.image_url && src !== product.image_url) {
          setSrc(product.image_url);
        }
      }}
    />
  );
}
