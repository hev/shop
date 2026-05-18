# Note for the mesh team — hev-shop user-visible failures, 2026-05-15

Three bugs showed up on https://hev-shop.com today (landing page categories
went static, product pages 404, classifier filter on /search returns ∅).
They all unwind to the same operational fact — **Aerospike has been
unscheduleable for ~2 days** — but the way layer-gateway *handles* that
unavailability is what turned a degraded cache into three different
application-visible failures. The cache outage is a config problem on our
side (missing `mesh-role=aerospike` NodePool); everything below is about
gateway behavior that we'd want to harden before another cache hiccup
hits a customer.

## What's actually broken in prod

```
$ kubectl get pod -n aerospike mesh-aerospike-0
NAME              READY   STATUS    RESTARTS   AGE
mesh-aerospike-0  0/2     Pending   0          2d2h
   Warning FailedScheduling: did not tolerate taint mesh-role=aerospike:NoSchedule
```

Every layer-gateway call that touches Aerospike fails after a 3-retry,
~10s client timeout. The gateway is logging that fact at the right level
(`Aerospike error: ... Timeout after 3 tries`), but several call sites
turn that warning into a hard caller-visible failure when they don't
need to.

## Three call-site behaviors that we'd like to revisit

### 1. `fetch_document` returns 503 on cache error instead of failing over to turbopuffer

`apps/layer-gateway/src/routes/fetch.rs:35-55`:

```rust
match state.aerospike.get(&namespace, &doc_id, ...).await {
    Ok(Some(attrs)) => return Ok(...),
    Ok(None)        => { /* fall through */ }
    Err(e) => return Err(AppError::ServiceUnavailable(format!(
                  "Aerospike unavailable: {}", e))),
}
```

A clean cache miss (`Ok(None)`) does fall through to turbopuffer and
backfills the cache. But a cache **error** (`Err(_)`) — which is what a
client timeout produces — gives up and returns 503. The doc fetch path
already knows how to read from turbopuffer; it just refuses to do so
when the cache itself is sick.

User-visible effect: `GET /v2/namespaces/amazon-products/documents/{asin}`
503s. The hev-shop indexer catches that as an `httpx.HTTPStatusError` and
maps it to a 404 (`indexer/app/main.py:201`), so the storefront
`/product/{asin}` page calls `notFound()`. From the user's perspective, a
product they just searched for and clicked is gone.

Suggested fix: treat `Err` the same as `Ok(None)` for the read path —
log it (we already do via `warn!`), fail over to turbopuffer, skip the
backfill. The 503 we have today violates the gateway's "Layer is a cache
in front of turbopuffer" contract. The matching batch path
(`fetch_many_documents`) has the same shape.

Worth also surfacing the degraded mode back to the caller — e.g. a
`layer.cache_status: "degraded"` field on the response (parallel to the
`layer.{stable_as_of, is_stable}` block we already add to `/metadata`),
or an `X-Layer-Cache: miss-on-error` header. Today the caller can't
distinguish "served fresh from turbopuffer because we wanted to" from
"served from turbopuffer because the cache is on fire" — both look
like a 200. Useful for client-side logging, dashboards, and
storefront-side decisions about whether to warn the user the page
might be stale.

### 2. `stage_document` makes Aerospike a hard write dependency

`apps/layer-gateway/src/routes/pipeline.rs:236-244`:

```rust
if let Err(e) = state.aerospike.put(&set_name, &chunk.id, &attrs).await {
    warn!(... "Failed to write chunk to Aerospike");
    return Err(AppError::Upstream(format!("Failed to write chunk: {}", e)));
}
```

Compare with `routes::upsert::upsert_or_delete` (the public
`POST /v2/namespaces/{ns}` route), which treats Aerospike as
best-effort and pushes through to turbopuffer:

```rust
if let Err(e) = state.aerospike.put_many(&namespace, &docs).await {
    warn!(... "Aerospike cache write failed (best-effort)");
}
```

The pipeline write path is strictly more important than the public
upsert path (it's how indexing works), and we made it strictly less
fault-tolerant. The logs are full of `502 Bad Gateway` responses to
`PUT /v2/pipelines/hev-shop-reviews/documents/...` with 10s latency,
each one matching a `Failed to write chunk to Aerospike` warn. The
review-classify workers retry → load goes up → Aerospike degrades
further. This is a textbook positive feedback loop on a cache that
ought to be best-effort.

Suggested fix: parallel the public upsert path — warn on Aerospike
failure, continue. The chunk is durably staged in the pipeline-store
(Postgres) anyway; Aerospike is just there to make the `get_chunks`
read fast and to seed downstream stages. (Owner-confirmed: staging IS
the cache-population point in the design — see §3 — so the write
itself should stay; it just shouldn't be a hard failure.)

### 3. Staging writes to the pipe-set, not the namespace set — so `fetch_document` can't see what staging populated

This is the one I had wrong in the first pass. **Staging is supposed to
be the cache-population path** — `stage_document` is exactly where
data enters Aerospike so later pipeline stages can claim/read it fast,
and the hev-shop indexer is already correctly staging before
embedding (`extraction.py` → `stage_product` → `claim` → `embed` →
`write_vectors`). The bug is that the two Aerospike sets don't line up:

`apps/layer-gateway/src/routes/pipeline.rs:225` (staging writes here):

```rust
let set_name = format!("pipe_{}", pipeline.target_namespace);
... state.aerospike.put(&set_name, &chunk.id, &attrs).await ...
// attrs = { "text": <chunk.text>, "metadata": <chunk.metadata blob> }
```

`apps/layer-gateway/src/routes/fetch.rs:36` (reads from here):

```rust
state.aerospike.get(&namespace, &doc_id, include_attrs.as_deref())
```

Staging fills `pipe_amazon-products` with one record per **chunk id**,
shaped `{text, metadata: {...}}`. `fetch_document` reads
`amazon-products` looking for one record per **document id**, shaped
`{title, image_url, category, ...}` flat. Two different keyspaces, two
different shapes — staging populates the cache, but not the cache that
namespace reads use.

Suggested fix: have staging also (or instead) write a namespace-shaped
record into the namespace set — e.g. `aerospike.put(&namespace,
&doc_id, &flatten(chunk.metadata))` alongside the existing
`pipe_<namespace>` write. With that in place, the moment hev-shop
finishes `stage_product` for an ASIN, `GET
/v2/namespaces/amazon-products/documents/{asin}` becomes a cache hit
with the full attribute set, regardless of whether `write_vectors`
has run yet. `write_vectors` then doesn't need to touch Aerospike at
all — staging owns cache population, vectors-write owns turbopuffer,
clean separation. (This also makes §4 a non-issue for the
indexed-by-our-pipelines case, because the seeded cache record is
fuller than what a field-values scan would later try to overwrite.)

### 4. Field-values origin scans poison the cache with partial attributes

`apps/layer-gateway/src/routes/scan.rs:497-530` — `execute_origin_scan`
for `ScanType::FieldValues` requests only the scanned field and
`_upserted_at` from turbopuffer:

```rust
let field_scan_attrs = match (scan_type, field) {
    (ScanType::FieldValues, Some(field_name)) =>
        Some(vec![field_name.to_string(), UPSERTED_AT_ATTR.to_string()]),
    _ => None,
};
...
// Backfill Aerospike with whatever turbopuffer returned
state.aerospike.put_many(namespace, &cache_docs).await
```

Then it backfills Aerospike with `{field_name, _upserted_at}` only —
overwriting any fuller record that might already be there for those
IDs. Subsequent `fetch_document` calls then hit `Ok(Some(attrs))` with
just `{category: "Electronics"}` and return that as the whole document.

We saw this directly: probing the live API,
`/v2/namespaces/amazon-products/documents/B00FI7TCGI?include_attributes=...`
returns `{"id":"B00FI7TCGI","attributes":{"category":"Electronics"}}` on
cache hit, but a fresh turbopuffer fetch has title, image_url,
description, etc.

This is also what the indexer comment in `indexer/app/main.py:326-329`
is working around — cache scans were "silently returning zero buckets",
so /meta was pinned to origin. With this current scan implementation,
the cache is actively *worse* than nothing for `documents/{id}` reads
because it stomps full records with thin ones.

Suggested fix: don't backfill Aerospike from a partial-attribute
turbopuffer scan. Either skip the backfill when `field_scan_attrs` is
constrained, or merge instead of overwrite (`put_many` semantics
today look like a full replace). A `put_many` that preserved existing
bins on conflict would also be useful for the tag-rollup upsert path
(see §5).

### 5. Origin scan is the only path that advances `cache_warmed_through` — deferring

Symptom: auto-mode `decide_auto` (scan.rs:314-342) sees `count_set ==
0`, never picks cache, always goes origin. Origin scans take ~56s for
`amazon-products` (264k docs at 1000/page through turbopuffer). The web
side's `META_TIMEOUT_MS = 4_000` in `web/lib/backend.ts:10` gives up
long before that, so the landing page silently falls through to
`FALLBACK_CATEGORIES`.

This is partly self-inflicted on the indexer side — the explicit
`source="origin"` pin was a workaround for §1+§4. Once §3 lands, the
indexer can move back to `source="auto"` and /meta should be fast.

**Tabled for a separate writeup** — the longer-term watermark
plumbing (advancing `cache_warmed_through` on every write rather than
only on scan completion) deserves its own design pass and isn't on the
critical path for today's user-visible breakage.

## Bonus: tags are missing from `/query` responses

Independent of the cache issue — search hits coming out of `/query`
don't include `tags`/`tag_counts`/`tag_samples` even though those fields
are in the namespace schema (`metadata.schema.tags: {filterable: true,
type: "[]unknown"}`). The hev-shop review-classify workers stage the
rollup as `upsert_vectors(namespace, [{id: asin, attributes:
{tags:..., tag_counts:..., tag_samples:...}}])`, which goes through the
public upsert path.

If turbopuffer is doing full-record replace on upsert (which is what
the gateway client looks like — we send an `UpsertDoc { vector,
attributes }` with no vector, no merge directive), the tag-only upsert
is wiping out the image-pipeline's `title`/`description`/`image_url`
on those docs. The Aerospike write would have the same problem if the
cache were up.

This would be worth confirming on the gateway side: do we have, or
should we add, partial-attribute upsert semantics — and does the
turbopuffer client today match what the hev-shop indexer assumes
(partial merge)? Our docs (`docs/guides/namespaces.md`) don't say.

## Summary of asks

| #  | Where                                 | Change                                                                                          |
| -- | ------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 1  | `routes/fetch.rs`                     | Treat Aerospike `Err` as miss; fail over to turbopuffer. Surface degraded mode in the response. |
| 2  | `routes/pipeline.rs::stage_document`  | Aerospike write best-effort, match `upsert_or_delete`. (Keep the write — it's the cache pop.)   |
| 3  | `routes/pipeline.rs::stage_document`  | Also write a namespace-shaped record so `fetch_document` actually finds what staging populated. |
| 4  | `routes/scan.rs::execute_origin_scan` | Don't backfill cache from partial-attribute scans.                                              |
| 5  | watermark plumbing                    | Deferred — separate writeup.                                                                    |
| 6  | upsert path semantics                 | Document / implement partial-attribute merge upserts.                                           |

(1)–(4) would make today's outage invisible to users.
(6) is the structural fix that gets the hev-shop indexer out of its
remaining workaround (the tag-rollup vs. image-pipeline attribute
collision).

— logged from `/Users/hev/workspace/hev/shop` after reading
`../mesh/apps/layer-gateway/src/routes/{fetch,scan,pipeline,upsert}.rs`
and the live `layer-gateway-7c6cfb68c6-vgzrb` / `hev-shop-api-...` logs.
