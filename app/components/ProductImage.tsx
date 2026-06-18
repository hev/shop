import Image from "next/image";
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
  const src = imageSrc(product);
  if (!src) return null;

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
    />
  );
}

function imageSrc(product: Product): string {
  const blob = product.image_blob?.trim();
  if (blob?.startsWith("blob://")) {
    const parsed = blob.slice("blob://".length).split("/");
    if (parsed.length === 2 && parsed[0] && parsed[1]) {
      return `/api/blobs/${encodeURIComponent(parsed[0])}/${encodeURIComponent(parsed[1])}`;
    }
  }
  return product.image_url;
}
