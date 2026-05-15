export type Product = {
  asin: string;
  title: string;
  description: string;
  category: string;
  image_url: string;
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
