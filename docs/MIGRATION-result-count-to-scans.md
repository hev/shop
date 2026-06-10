# Heads-up: `/result-count` is gone — move radius counts to `/scans`

**Date:** 2026-06-07
**From:** layer team (RFC 0030, landed on `layer` `main` as `dd81e54`)
**Affects:** `search/` (Python backend), `tests/` (Go e2e client), the
frontend footer link, and the shop search OpenAPI doc.

## TL;DR

The gateway folded result count into the scan surface. `POST
/v2/namespaces/{ns}/result-count` **no longer exists** — its vector arm is now
a **radius (`ann`) scan** on `POST /v2/namespaces/{ns}/scans`, and `max_distance`
is renamed **`radius`**. This is a hard cutover (pre-1.0, no compat shim): once
you bump the `hevlayer` Python client, `search/app.py` stops importing, because
`result_count`, `ResultCountRequest`, and `VectorResultCountQuery` were deleted
from the client.

Shop's `_vector_count` is the one real caller. The change is mechanical — same
fan-out, same numbers, new request/response skin — plus one new field worth
surfacing (`approximate`).

## What changed at the gateway

| Before | After |
| --- | --- |
| `POST /v2/namespaces/{ns}/result-count` | `POST /v2/namespaces/{ns}/scans` with `mode: "count"` |
| `query: { vector, max_distance }` | `ann: { vector, radius }` |
| `query: { field, fts }` (FTS arm) | `fts: { field, query }` |
| `mode: "bounded" | "exhaustive"` | `exhaustive: false | true` (bounded is the default) |
| `ResultCountResponse` | `ScanCountResponse` (adds `served_by`, `approximate`) |
| client `layer.result_count(...)` | client `layer.create_scan(...)` |

`max_distance` → `radius` is just a rename of the same distance ceiling; your
`0.4` default carries over unchanged. `radius` is still required and finite.

## 1. `search/app.py` — `_vector_count` (the critical change)

Imports:

```diff
 from hevlayer import (
     AsyncHevlayer,
-    ResultCountRequest,
+    AnnScan,
+    CreateScanRequest,
     CreateSnapshotRequest,
     QueryRequest,
-    VectorResultCountQuery,
 )
```

The call:

```diff
-    response = await layer.result_count(
-        namespace,
-        ResultCountRequest(
-            query=VectorResultCountQuery(vector=vector, max_distance=max_distance),
-            filters=filters,
-        ),
-        with_perf=True,
-    )
+    response = await layer.create_scan(
+        namespace,
+        CreateScanRequest(
+            mode="count",
+            ann=AnnScan(vector=vector, radius=max_distance),
+            filters=filters,
+        ),
+        with_perf=True,
+    )
```

`response.data` is now a `ScanCountResponse`. Every field your `CountInfo`
mapping reads is still there: `count`, `bounded`, `timed_out`,
`shards_saturated`, `shards_total`. So the `CountInfo(...)` construction below
the call does not need to change — keep your internal `max_distance` field name
on `CountInfo` if you like; only the gateway request uses `radius`.

> Note: `create_scan` is typed as a union (`ScanCountResponse | ScanJob`)
> because the same endpoint also creates async ID jobs. In `mode: "count"` you
> always get a `ScanCountResponse` back.

## 2. New response field: `approximate` (and what `bounded` means now)

`ScanCountResponse` adds two fields over the old shape:

- `served_by` — always `"origin"` for `ann`/`fts` scans (they have no snapshot
  or cache path). Informational.
- `approximate` — **`true` on every radius (`ann`) count.** ANN recall means
  the index's membership of the distance ball is itself fuzzy, *independent of
  saturation*.

Your existing "render `≥N` when `bounded`" rule still holds: `bounded` means a
shard saturated its `top_k` cap, so `count` is a lower bound. What's new is that
`approximate` and `bounded` are now independent — an `ann` count can be
`bounded: false` yet still `approximate: true`. If you want to be precise in the
UI, a radius count is always an estimate ("~") and additionally a lower bound
("≥") when `bounded`. Surfacing `approximate` on `CountInfo` is optional but
recommended.

## 3. Frontend (`app/lib/backend.ts`, `app/app/search/page.tsx`)

These talk to **shop's own** `/search` API, not the gateway directly, so they
only change if you rename the field on your public surface. You can keep
`max_distance` in shop's API and types — it's your contract, not the gateway's.
If you'd rather mirror the gateway's `radius` naming, that's a separate, optional
cleanup in `search/models.py` + `search/openapi.json` + the TS types.

## 4. `tests/` (Go e2e client)

`tests/client/searchapi/oapi.gen.go` is generated and its docstrings still
describe a `/v2/namespaces/{ns}/result-count` fan-out. Regenerate it against the
shop search OpenAPI once you've updated `search/openapi.json`. The
`tests/cmd/search.go` `--with-count` flag (and its `--max-distance` ceiling)
keeps working through shop's `/search` API; nothing there calls the gateway
directly, so only the generated wording needs refreshing.

## 5. Footer docs link (404 fix)

`app/components/Footer.tsx` links "Result counts" to `${DOCS}/api/result-count`,
which is now a deleted page. Point it at the scan page:

```diff
-          <FooterLink href={`${DOCS}/api/result-count`}>Result counts</FooterLink>
+          <FooterLink href={`${DOCS}/api/scans`}>Result counts</FooterLink>
```

## 6. `search/openapi.json` doc strings

The `CountInfo` description and the `with_count` field doc both reference
"`/v2/namespaces/{ns}/result-count`". Swap that wording for "a `/v2/namespaces/{ns}/scans`
radius (`ann`) count" so your published spec matches reality.

## If you ever add a full-text count

You don't today (shop only does vector/radius counts), but for the record: a
BM25 count is the `fts` selector — `create_scan(ns, CreateScanRequest(mode="count",
fts=FtsScan(field="title", query="..."), filters=...))`. `fts` counts are
**exact** (no `approximate` flag); `ann` counts are approximate. Both honor
`exhaustive` and the `timeout_seconds` deadline, and both run origin-only.

## References

- Scan docs (the single on-demand surface now): `<layer-docs>/api/scans` —
  selector/mode matrix, `fts`/`ann` examples, `exhaustive`, `approximate`.
- RFC: `layer/docs/rfcs/0030-fold-result-count-into-scan.md`.
- Cutover commit: `layer@dd81e54`.

Ping the layer team if anything in your fan-out doesn't have a clean
equivalent — the radius scan is a lift-and-shift of the exact same
scatter/gather, so it should map 1:1.
