// Pure, client-safe helpers shared by search chips and the header search-bar
// dropdown. Nothing server-only is imported here, so the client bundle can pull
// it in without dragging in backend adapters.

export function searchHref(query: string): string {
  return `/search?q=${encodeURIComponent(query)}`;
}

export function truncateQuery(query: string, max = 40): string {
  return query.length > max ? query.slice(0, max - 1).trimEnd() + "…" : query;
}
