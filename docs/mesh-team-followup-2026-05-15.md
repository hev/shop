# hev-shop → mesh team: post-deploy follow-up, 2026-05-15

Hi mesh team —

Quick follow-up after rolling out the indexer-side changes against your
new build. §§1, 2, 3, 4, 6 are visibly live (verified `x-layer-cache`
header, no more 503s, dropped the `source="origin"` pin on /meta, tag
rollup switched to PATCH). Two issues are still blocking the
storefront recovery and I think they're both mesh-side.

## 1. Warm-scan backfill isn't taking effect on pre-existing thin records

To clean the cache poisoning from old partial scans (§4) I fired
`POST /v2/namespaces/amazon-products/warm`. The scan ran end-to-end:

```
Scan completed namespace=amazon-products
  scan_id=b17a9f7c-31c3-4ec7-b5d4-7f96ef2491a0
  docs=265707 source=Origin stable_as_of=Some(1778882484876)
```

No `Aerospike backfill failed during scan` warnings in the surrounding
log window, so `put_many` reported success on every page. But fetching
the doc afterward still returns the thin pre-fix record:

```
GET /v2/namespaces/amazon-products/documents/B00FI7TCGI
  ?include_attributes=title,image_url,category,description,asin
→ HTTP 200, x-layer-cache: hit
→ {"id":"B00FI7TCGI","attributes":{"category":"Electronics"}}
```

`title`, `image_url`, `description`, `asin` are all in turbopuffer for
this doc and would have come back in a `field_scan_attrs=None`
full-document scan. They never landed in Aerospike — at least not
under the key/bin shape that `fetch_document` reads.

Two possibilities I can think of, both yours to confirm:

- **`put_many` is merging into existing records rather than replacing
  them**, and the existing record has only `{category}` so the new
  bins don't take. Mesh's note said current semantics look like full
  replace; this would mean they aren't.
- **Backfill writes to a different bin set than `get` reads from**
  (e.g. a versioned bin name, a different set suffix). The
  `AEROSPIKE_SET_PREFIX=tpuf_` on the gateway pod made me check —
  individual `aerospike.put`/`get` paths use `&namespace` directly, so
  this should be a single set, but worth a look.

A workaround on our side would be to explicitly delete every
`amazon-products` cache record and let pull-through repopulate, but
we'd rather not paper over a backfill that's silently failing to land.

## 2. Aerospike scans return `FailForbidden`

This is what's making cache scans return zero and probably what's
keeping auto-mode stuck on origin:

```
WARN routes::scan: Scan failed namespace=amazon-products
  scan_id=dce840d3-8ada-468a-a94d-1df54670e926
  error=Aerospike scan failed: Aerospike error: scan record error:
        Server error: FailForbidden, In Doubt: false, Node: 10.0.10.64:3000
```

Node `10.0.10.64` is `mesh-write-buffer-0` in the `mesh` namespace —
the actual Aerospike layer-gateway is wired to (`AEROSPIKE_HOSTS=
mesh-write-buffer.mesh.svc.cluster.local:3000`). Singles work
(`aerospike.get` returns Ok(Some(...)) on every doc fetch), scans
fail. This looks like an Aerospike role/ACL config — the
gateway's role isn't permitted to issue scan ops against the
`hevlayer` Aerospike namespace.

Side note: the `mesh-aerospike-0` pod in the `aerospike` namespace has
been `Pending` for 2+ days, which sent us down a rabbit hole earlier
today thinking it was the cache outage. It's a red herring — nothing
in the live config points at it. Either delete it or document that
`mesh-write-buffer` superseded it.

## Impact on the storefront

| Symptom                       | Status                                                                |
| ----------------------------- | --------------------------------------------------------------------- |
| `/product/{asin}` thin attrs  | Blocked on issue #1 — cache won't repopulate with full records        |
| `/meta` slow (~25s) + scan storm | Partly blocked on #2 — auto-mode can't pick cache, every call origins through turbopuffer |
| Landing categories static     | Web-side 4s timeout vs /meta's 25s — we can fix that on our end       |
| `/search` tag filter ∅        | Tag rollup hasn't run yet; PATCH path queued — will retest once #1 is sorted |

Happy to pair on either — or drop me an Aerospike role tweak / a
small put_many test case if that helps you isolate #1.

— Adam (hev-shop)
