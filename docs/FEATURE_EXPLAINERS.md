# Feature explainers — "How it works" across the storefront

A reusable affordance that lets a curious shopper open any result set and see
*how* it works — the Layer capability behind it, the gateway call shape, and
links to the docs. Built first for the browsing rail
(`docs/BROWSING_RAIL_DESIGN.md`), designed to apply to every Layer-powered
surface.

Implementation: `app/components/FeatureExplainer.tsx` (the affordance) +
`app/lib/feature-explainers.ts` (the content registry).

## The concept

Every result set on the site is really a *Layer capability wearing a storefront
hat* — vector search, query-by-id recommendations, multi-query fusion, cached
reads, snapshots, freshness watermarks. The perf badges already hint at this in
the supporting register. The explainer makes it legible without leaving the
page:

- **Treatment** — each result-set header carries a small, consistent
  `[ ⓘ How it works ]` pill. Same shape everywhere, so it reads as "this
  section is a Layer feature you can inspect."
- **Detail** — clicking opens a popover with a plain-language summary, a
  mechanism list (the fields/models/call mode), an optional gateway call shape,
  and **doc links** that deep-link into hevlayer.com.

### Design constraints (from `CLAUDE.md`)

- Supporting evidence, not the main event. The pill is quiet (ghost ring, ink
  text); the storefront still reads as a storefront. This is the same register
  as `LayerPerfBadge` / `StableAsOfBadge`.
- One registry, many mounts. Copy lives in `lib/feature-explainers.ts` so the
  vocabulary stays consistent and adding a surface is one entry + one
  `<FeatureExplainer id=… />`. (Keeping copy out of JSX also sidesteps the
  unescaped-entity lint.)
- Accurate or absent. The mechanism and doc links must match real gateway
  behavior. `getFeatureExplainer` returns `undefined` for an unknown id and the
  component renders nothing — no broken affordance.

## Component contract

```tsx
<FeatureExplainer
  id="browsing-rail"   // registry key
  align="left|right"   // which edge the popover anchors to (default right)
  stat="3 queries → RRF → 8 results"  // optional live, per-instance line
/>
```

- Client component: owns popover open/close, outside-click, and Esc.
- `stat` is the one dynamic hook — static copy stays in the registry, only a
  runtime number (e.g. the browsing rail's fused count) is threaded in.
- `align="left"` for left-positioned kickers (search, recent searches) so the
  popover doesn't overflow; `right` (default) for right-aligned headers.

## Registry entry shape

```ts
type FeatureExplainer = {
  id: string;
  title: string;        // popover header — the feature's name
  summary: string;      // 1–2 plain sentences
  mechanism: { label: string; detail: string }[];  // field/model/call rows
  call?: string;        // optional gateway call shape, mono
  docs: { label: string; href: string }[];         // deep links to hevlayer.com
};
```

## Rollout map

Doc routes verified against `../layer/site/src/content/docs`.

| id | Surface | Mounted | Capability · doc |
|---|---|---|---|
| `browsing-rail` | Homepage "Similar to your browsing" | ✅ | multi-query + RRF · `api/query#multi-query` |
| `visually-similar` | `/product/[asin]` "You might also like" | ✅ | query by id · `api/query#query-by-id` |
| `search` | `/search` results header | ✅ | vector ANN + stable read · `api/query` |
| `trending` | Homepage Trending chips | ✅ | search-history + reduce UDF · `api/search-history`, `kubernetes/function-crd` |
| `product-fetch` | `/product/[asin]` doc-fetch detail | ✅ | cached fetch · `api/query#fetch`, `api/warm-cache` |
| `drops` | `/drops` page header | ✅ | checkpoint label + freshness · `api/checkpoints`, `api/pipelines` |
| `categories` | Homepage filter row | ✅ | snapshots + metadata · `api/snapshots` |

All seven surfaces are now mounted. That's the intended shape of the rollout:
the registry is the broad artifact, mounts land per surface — adding a surface
stays one entry + one `<FeatureExplainer />`.

The slim dark **drop band** under the hero (`DropBand.tsx`) intentionally does
*not* carry the pill: it's a one-line teaser on `bg-ink-900`, and the pill's
quiet light styling (ghost ring, ink text) is built for light section headers,
not a dark strip. The canonical drops surface — the `/drops` page header — is
where `drops` mounts. A dark-background pill variant is the prerequisite if we
ever want the band to carry it.

## Adding a new explainer

1. Add an entry to `EXPLAINERS` in `lib/feature-explainers.ts` (verify each
   `docs` href against the live docs site).
2. Drop `<FeatureExplainer id="your-id" align=… />` into that surface's header,
   beside the kicker or perf badge.
3. If the surface has a live stat worth surfacing, pass it as `stat`.
