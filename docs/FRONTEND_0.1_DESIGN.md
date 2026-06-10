# Frontend 0.1 design — Drops & Personal recent searches

UI design notes for the two storefront surfaces around catalog drops and
recent searches. The implementation lives in `app/app/drops/page.tsx`,
`app/components/DropBand.tsx`, `app/components/SearchBar.tsx`,
`app/components/RecordSearch.tsx`, and `app/lib/recent-searches-local.ts`.

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
   (`app/components/Header.tsx`). The nav stays three text links + cart;
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

- `backendSearch` accepts `catalogRunId?: string`, sent as `catalog_run_id`.
- An active-filter chip renders above results, visually distinct (mono label):
  `drop: catalog-2026-06-07 ×`. Clicking × removes the param. The drop filter
  composes with `q` through the same URLSearchParams plumbing used by search
  pagination.
- An empty `q` with a `drop` param is valid: `/search` uses a filtered
  namespace query for drop-only browsing, and vector search when `q` is present.

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

- `app/app/drops/page.tsx` — new route
- `app/components/DropBand.tsx` — homepage strip (server component)
- `app/components/Header.tsx` — nav link
- `app/lib/backend.ts` — `backendDrops()`, `catalogRunId` on `SearchOptions`
- `app/app/search/page.tsx` — drop filter chip + param plumbing

---

## 2. Personal recent searches

RFC 0040 split the old "recent searches" idea into:

- **Your recent searches** — this browser's submitted queries, private and
  client-side.
- **Trending** — everyone's queries, aggregated by the Layer reduce UDF; see
  `docs/TRENDING_DESIGN.md`.

This section covers the personal half only.

### Header dropdown (search-bar suggestions)

#### What the user can do

Focus the search bar with an empty field and see queries this browser has run
before. Arrow-key or click one to run it again.

#### Interaction

- **Open** on input focus *when the field is empty* (suggestions, not
  autocomplete — 0.1 does not filter the list against the typed prefix; that's
  a later refinement). Re-opens on focus, closes on blur/submit.
- **Keyboard:** ↓/↑ move a highlight through the rows, Enter runs the
  highlighted query (falls back to the typed text when nothing is highlighted),
  Esc closes without losing focus. Reuse the outside-click + Esc pattern already
  in `FeatureExplainer`.
- **Anchor:** absolutely positioned under the input inside `SearchBar`'s
  existing `relative w-full` wrapper, matched to the input width, `z-50`. This
  is the fix for the original "competes with the announcement bar" blocker — the
  dropdown overlays at a high z-index rather than pushing layout.
- **Invisible-when-empty:** no local history → no dropdown, ever. The search
  bar is unchanged when there's nothing to suggest.

#### Data path

No backend route is involved.

- `RecordSearch` mounts on `/search` and records the active submitted query.
- `recent-searches-local.ts` trims, collapses whitespace, dedupes
  case-insensitively, caps at 8, persists to localStorage, and dispatches a
  window event.
- `SearchBar` reads that local list on mount, on focus, and whenever the event
  fires.

#### Reuse

The dropdown uses `searchHref()` and `truncateQuery()` from
`app/lib/search-ui.ts`. It intentionally carries no `FeatureExplainer`: this is
a private UX nicety, not a Layer capability. The Layer story is the homepage
`Trending` section.

#### Forward compatibility

This is the literal interaction that becomes the chat input's suggested-prompt
chips in the agentic rewrite (issue #3, §3 below).

### Files

- `app/lib/recent-searches-local.ts` — localStorage personal history
- `app/components/RecordSearch.tsx` — records submitted queries from `/search`
- `app/components/SearchBar.tsx` — focus-state listbox + keyboard nav
- `app/lib/search-ui.ts` — `searchHref()` + `truncateQuery()`, shared client-safe
  helpers used by the dropdown and Trending chips

---

## 3. Forward compatibility

- **Agentic homepage (issue #3).** Both surfaces survive the chat-first
  rewrite: personal recent searches become the suggested-prompt chips above the
  chat input (same local data), and the drop band becomes a
  rail above or beside the chat column. Neither should be built as
  hero-internal markup — keep them as standalone components mounted by
  the page so the rewrite re-mounts rather than re-implements them.
- **Browsing rail (issue #7).** Built — see `docs/BROWSING_RAIL_DESIGN.md`.
  Landed on the **homepage** (under the drop band) rather than the originally
  reserved `/product/[asin]` slot: it's a session-wide taste signal seeded by
  the whole browsing history, so it's strongest where there is no single seed
  product. Powered by the hev layer TypeScript client's array `searchById`
  (multi-query + RRF over the localStorage history); mock-only for 0.1, with a
  contained swap to gateway-backed queries when the `hevlayer` TypeScript
  package is available to the storefront build. Each result set now carries a
  "How it works" explainer — see
  `docs/FEATURE_EXPLAINERS.md`.
- **`/drops` ingress.** The top-level path routes to `hev-shop-search` in
  `../layer/infra/ingress/hev-shop/`.
