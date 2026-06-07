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
  if (!product.image_url) return null;

  return (
    <Image
      src={product.image_url}
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
