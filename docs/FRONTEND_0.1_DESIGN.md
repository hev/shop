# Frontend 0.1 design — Drops & Recent searches

UI design notes for the two storefront surfaces around catalog drops and
recent searches. The implementation lives in `web/app/drops/page.tsx`,
`web/components/DropBand.tsx`, `web/components/RecentSearches.tsx`, and
`web/lib/backend.ts`.

Design constraints carried over from `CLAUDE.md`:

- These are product affordances first, pipeline evidence second. The Layer
  mechanics (perf badges, `stable_as_of`) stay in the supporting-detail
  register already used on search and product pages.
- Both surfaces must degrade to *invisible* when their endpoint is missing,
  errors, or returns nothing — no empty-state placeholders on the homepage.

---

## 1. Drops ("What's new")

### What the user can do

See which catalog refreshes landed recently, and browse exactly the
products from one refresh.

### IA: three placements, one route

1. **Route `/drops`** — the canonical surface. A list of recent catalog
   runs, newest first. Each row links to `/search?drop={run_id}`.
2. **Header nav** — add `Drops` between `Shop` and `All`
   (`web/components/Header.tsx`). The nav stays three text links + cart;
   no mega-menu.
3. **Homepage band** — a slim single-line strip between the hero and the
   categories section showing only the *latest* run:

   ```
   FRESH VECTORS   catalog-2026-06-07 — 1,204 products re-embedded last night · browse the drop →
   ```

   Rendered server-side from the same `/drops` response (first entry).
   Hidden entirely when the fetch fails or the list is empty.

### `/drops` page layout

Same page skeleton as `/search` (max-w-7xl, uppercase kicker, display
heading):

```
DROPS
Nightly catalog refreshes
Every night a CronJob re-embeds the launch corpus. Each drop below is one
catalog_run_id — click through to browse only those vectors.   [/drops perf badge]

┌────────────────────────────────────────────────────────────────┐
│ catalog-2026-06-07          1,204 products      stable 06-07 09:14 UTC │  → /search?drop=catalog-2026-06-07
│ catalog-2026-06-06          1,198 products      stable 06-06 09:12 UTC │
│ …                                                              │
└────────────────────────────────────────────────────────────────┘
```

- Rows are full-width links styled like the existing card ring pattern
  (`rounded-2xl bg-white ring-1 ring-ink-200`), run ID in `font-mono`.
- The newest row gets the accent kicker `LATEST`.
- Empty state (endpoint up, no runs yet): reuse the dashed-border empty
  card from search — "No drops yet. The CronJob runs nightly; check back
  after the next refresh."

### Search integration

`/search?drop={run_id}`:

- `backendSearch` gains `catalogRunId?: string`, sent as `catalog_run_id`
  (WS2 adds it to `SearchRequest`).
- An active-filter chip renders above results, visually distinct (mono label):
  `drop: catalog-2026-06-07 ×`. Clicking × removes the param. The drop filter
  composes with `q` through the same URLSearchParams plumbing used by search
  pagination.
- An empty `q` with a `drop` param is valid: "everything in this drop".
  (Backend note: this needs `/search` to accept filter-only queries, or
  the page substitutes the drop's category as the query — decide when
  WS2 lands; the UI contract is just "the URL works".)

### Response contract consumed by the frontend

```jsonc
// GET /drops
{
  "drops": [
    { "run_id": "catalog-2026-06-07", "product_count": 1204, "stable_as_of": 1780000000000 }
  ],
  "layer_perf": { "latency_ms": 12, "cache_status": "hit" }  // nullable
}
```

Frontend treats `drops` as newest-first; tolerates missing
`stable_as_of` (renders without the timestamp).

### Files (when built)

- `web/app/drops/page.tsx` — new route
- `web/components/DropBand.tsx` — homepage strip (server component)
- `web/components/Header.tsx` — nav link
- `web/lib/backend.ts` — `backendDrops()`, `catalogRunId` on `SearchOptions`
- `web/app/search/page.tsx` — drop filter chip + param plumbing

---

## 2. Recent searches

### What the user can do

See what people are actually asking the index, and run one of those
queries with a click.

### Placement

Homepage, directly under the hero CTA buttons — a single restrained chip
row in the existing pill style:

```
RECENTLY ASKED   [cozy reading corner] [wireless headphones] [something brass and warm] …
```

- Uppercase kicker matches the categories row (`filter` kicker).
- Chips are the existing pill pattern (`rounded-full border border-ink-200
  bg-white px-4 py-1.5 text-sm`), each linking to `/search?q={query}`.
- Cap at 8 chips, single line of wrap; truncate individual queries at
  ~40 chars with ellipsis.
- Server component with a short timeout (match `META_TIMEOUT_MS`);
  hidden on error, empty list, or endpoint missing.

Not in the header for 0.1: a dropdown under `SearchBar` needs client
focus-state work and competes with the announcement bar. The homepage row
is the restrained version; the header dropdown is a natural follow-up.

### Response contract consumed by the frontend

```jsonc
// GET /search/recent?limit=8
{
  "queries": ["cozy reading corner", "wireless headphones"],
  "layer_perf": { "latency_ms": 9, "cache_status": null }  // nullable
}
```

Backend owns normalization (dedupe, case/whitespace, drop empty/overlong);
the frontend renders verbatim.

### Files (when built)

- `web/components/RecentSearches.tsx` — new server component
- `web/app/page.tsx` — mount under hero CTAs
- `web/lib/backend.ts` — `backendRecentSearches()`

---

## 3. Forward compatibility

- **Agentic homepage (issue #3).** Both surfaces survive the chat-first
  rewrite: recent searches become the suggested-prompt chips above the
  chat input (same component, same data), and the drop band becomes a
  rail above or beside the chat column. Neither should be built as
  hero-internal markup — keep them as standalone components mounted by
  the page so the rewrite re-mounts rather than re-implements them.
- **Browsing rail (issue #7).** Reserved slot: below "Visually similar"
  on `/product/[asin]`. No work now; blocked on layer-gateway
  query-by-document-ID.
- **`/drops` ingress.** The top-level path routes to `hev-shop-search` in
  `../layer/infra/ingress/hev-shop/`. `/search/recent` rides the existing
  `/search*` prefix.
