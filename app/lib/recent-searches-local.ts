// Client-side personal search history: the queries *this browser* has run,
// newest first. RFC 0040's "Your recent searches" surface (the header search-bar
// dropdown) — the personal half of the old "recent searches", split out from the
// aggregate "Trending" surface (see lib/trending.ts).
//
// Deliberately a mirror of recently-viewed.ts: localStorage, no account, no
// gateway round-trip, no auth (tags are caller-controlled and unusable for
// per-user isolation). Browser-only — every accessor guards `window` so it is
// inert during SSR.

const STORAGE_KEY = "hev-shop:recent-searches";
const MAX_QUERIES = 8;

// Fired on the window whenever the list changes so a mounted dropdown can
// refresh without a navigation.
export const RECENT_SEARCHES_EVENT = "hev-shop:recent-searches-changed";

function normalizeQuery(query: string): string | null {
  const normalized = query.trim().replace(/\s+/g, " ");
  return normalized.length > 0 ? normalized : null;
}

function read(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((v): v is string => typeof v === "string" && v.length > 0)
      .map((v) => normalizeQuery(v))
      .filter((v): v is string => v !== null);
  } catch {
    return [];
  }
}

function write(items: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    window.dispatchEvent(new Event(RECENT_SEARCHES_EVENT));
  } catch {
    // private mode / quota exceeded — suggestions are best-effort.
  }
}

// Move `query` to the front (newest first), dedupe case-insensitively, cap at
// MAX_QUERIES, then persist to STORAGE_KEY and dispatch RECENT_SEARCHES_EVENT so
// a mounted dropdown refreshes. Mirror recently-viewed.ts's read→transform→write.
export function recordSearch(query: string): void {
  const normalized = normalizeQuery(query);
  if (!normalized) return;
  const key = normalized.toLocaleLowerCase();
  const existing = read().filter((item) => item.toLocaleLowerCase() !== key);
  write([normalized, ...existing].slice(0, MAX_QUERIES));
}

export function getRecentSearchesLocal(limit = MAX_QUERIES): string[] {
  return read().slice(0, limit);
}
