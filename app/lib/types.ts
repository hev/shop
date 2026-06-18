export type Product = {
  asin: string;
  title: string;
  description: string;
  category: string;
  image_url: string;
  image_blob?: string;
  price: number | null;
  rating: number;
  rating_count: number;
};

export type SearchResponse = {
  query: string;
  results: Product[];
  took_ms: number;
};

export type SimilarResponse = {
  asin: string;
  results: Product[];
  took_ms: number;
};
