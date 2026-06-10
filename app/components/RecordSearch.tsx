"use client";

import { useEffect } from "react";
import { recordSearch } from "@/lib/recent-searches-local";

// Mounted on the search results page. Records the active query into the
// localStorage personal history that feeds the header search-bar's "Your recent
// searches" dropdown (RFC 0040 Phase 0). The sibling of RecordView for the
// browsing rail. Renders nothing.
export function RecordSearch({ query }: { query: string }) {
  useEffect(() => {
    if (query.trim()) recordSearch(query);
  }, [query]);
  return null;
}
