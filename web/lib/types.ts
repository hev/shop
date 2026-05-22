export type Product = {
  asin: string;
  title: string;
  description: string;
  category: string;
  // Original Amazon CDN URL; durable source-of-truth pointer kept on the
  // product attributes, also used as the browser-side fallback if the blob
  // route 404s.
  image_url: string;
  // Storefront image src — points at the public hev-shop API proxy, which
  // 302s to the Aerospike-backed blob route on the layer gateway. Resolved
  // at server-render time so the URL embedded in HTML is absolute. Optional
  // so mock-mode (no backend) can keep using image_url directly.
  image_src?: string;
  price: number | null;
  rating: number;
  rating_count: number;
  tags?: string[];
  tag_counts?: Record<string, number>;
  tag_samples?: Record<string, string[]>;
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

export type ReviewHit = {
  id: string;
  dist: number | null;
  review_id: string;
  asin: string;
  chunk_idx: number;
  text_chunk: string;
  rating: number | null;
  title: string;
  helpful_vote: number;
};

export type ReviewSample = {
  review_id: string;
  asin: string;
  title: string | null;
  text: string;
  rating: number | null;
};

export const REVIEW_TAGS = [
  "Buy it for life, no regrets",
  "Falls apart fast",
  "Value Leader",
  "Overpriced",
  "Worth the splurge",
  "Good but...",
  "Setup nightmare",
  "Wish I'd bought sooner",
  "Better in person",
  "Photos misleading",
  "Beginner friendly",
] as const;
