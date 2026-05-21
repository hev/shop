# hev-shop → layer team: binary blobs in the document cache

Hi —

We want to store product image bytes (JPEGs, 10–100 KB each, ~1.5M
products) in the Aerospike doc cache so the storefront can serve them
with a ~2 ms backend lookup. Today the gateway document model is
JSON-only end-to-end, so this needs a layer-side change. Filing this
so the team can review the shape before we cut tickets.

## Why we want it in the doc cache (not S3 or a CDN)

The demo story is "Layer makes one ingest fan out to product vectors,
review vectors, review tags, *and* the product image bytes — all served
from one place with cache-tier latency." Co-locating the bytes with the
existing per-doc attributes makes that story tight. We're explicitly
*not* trying to build a general blob store — just one more typed
attribute on the existing doc shape.

We've already accepted the storage cost (smallest NVMe nodes we'd run
are ~500 GB; ~1.5M × 50 KB ≈ 75 GB fits comfortably).

## Proposed doc model change

Extend `UpsertDocument` / `DocumentResponse` in
`apps/layer-gateway/src/models.rs` with a new optional field:

```rust
#[derive(Debug, Deserialize, Serialize)]
pub struct Blob {
    /// base64 on the wire, raw bytes in Aerospike
    pub data: String,
    pub content_type: String,
}

pub struct UpsertDocument {
    pub id: String,
    pub vector: Option<Vec<f64>>,
    pub attributes: HashMap<String, Value>,
    #[serde(default)]
    pub blobs: HashMap<String, Blob>,   // new
}
```

Names match the existing `attributes` map (per-doc keyspace). Most
docs will have one entry, e.g. `"image"`. Keeping it a map lets us
add thumbnails or variants later without a schema bump.

Wire format is base64-in-JSON for write symmetry with the rest of the
upsert payload. The 33% inflation only hits the upsert request body;
storage and reads stay binary.

## Storage: native Aerospike blob bins

In `clients/aerospike.rs`, `doc_to_bins()` currently funnels everything
through `json_to_aero()` and packs it into a single `"attrs"` bin.
Blobs should bypass that path and write one bin per blob key as
`aerospike::Value::Blob`:

- bin name: `blob:{key}` (e.g. `blob:image`)
- bin value: `Value::Blob(bytes)`
- bin name: `blobct:{key}` for content-type as `Value::String`

`get_raw`/`put_raw` already prove the binary path works. We're asking
to surface it through the typed doc model rather than a sidecar
keyspace so the embed-products write stays atomic with the vector
write.

Per-record limit is well under Aerospike's 1 MB default write-block
ceiling, so no config change should be needed. Worth a sanity assert
on `data.len()` (we'd suggest 512 KB hard cap, 413 if exceeded).

## Read path: dedicated streaming endpoint

The whole point is fast lookup, so don't make us JSON-decode +
base64-decode on every request. New route:

```
GET /v2/namespaces/{ns}/documents/{id}/blobs/{key}
  → 200 application/octet-stream (Content-Type from blobct:{key} bin)
  → 304 with ETag (id+key+digest) for browser caching
  → 404 if doc or blob bin missing
```

`FetchManyResponse` and `QueryResult` should *not* include blob bytes
by default — that would balloon every search response. If we ever need
to inline them, an opt-in `include_blobs: Vec<String>` mirroring
`include_attributes` is fine, but we don't need it for v1.

## Turbopuffer persistence: blobs are aerospike-only

This is the part most worth pushing back on before you build it.

The current doc model is symmetric — what lands in Aerospike also
lands in turbopuffer, because Aerospike is a pull-through cache.
Blobs break that symmetry, and we think they *should*:

- Turbopuffer isn't designed for 50 KB attribute payloads. Indexing
  them costs more and buys nothing — nothing queries on image bytes.
- For our use case, the source of truth is the original Amazon image
  URL. If Aerospike loses the bin (eviction, restart, namespace
  rebuild), the right answer is to refetch from source, not to drag
  it through tpuf.

Concretely: gateway writes `blobs` to Aerospike only, skips them on
the turbopuffer upsert, and on read returns 404 if the bin is absent.
We'll handle repopulation in our pipeline (see below) — no
gateway-side refetch needed in v1.

This does mean adding the concept of "Aerospike-local fields" to the
doc model. It's a real semantic addition and worth being explicit in
the response shape (e.g., docs returned from a query carry attributes
from tpuf; blob endpoints serve from Aerospike only). Vector is
already half-asymmetric (`PatchDocument` omits it), so there's
precedent.

If you'd rather keep the model strictly symmetric and persist blobs
through tpuf too, say so — we'll eat the storage. But we don't think
it earns its keep.

## What hev-shop does with this

1. **`embed-products` stage** (`indexer/app/pipeline.py`) already
   fetches the image to feed `CLIPImageEmbedder`. We'll keep the bytes
   and include them in the same upsert that writes the vector. One
   write, one disposition.
2. **Image fetch failure handling:** we already eat occasional Amazon
   CDN misses for the embed step. We'll emit a `blob_fetch_failed`
   counter and write the doc without the blob — the storefront falls
   back to the original Amazon URL on 404.
3. **Web read path:** `web/lib/backend.ts` proxies to
   `hev-shop-api`, which proxies to the new gateway blob route. We'll
   set long `Cache-Control: public, immutable` headers and let the
   browser do most of the work; the ~2 ms backend matters for the
   first hit and for the demo dashboard.

We'll also need a one-shot backfill to populate blobs for the docs
already indexed. New stage `backfill-images` modeled on the existing
backfill shape — not asking for layer changes for that, it just rides
the new upsert path.

## Out of scope for v1

- Server-side resizing / thumbnail generation.
- Populate-on-miss inside the gateway. The web side can do the
  fallback to Amazon URL; gateway stays dumb.
- Blob TTL / per-blob eviction policy distinct from the doc's TTL.
- `include_blobs` opt-in on query/fetch.

## Implementation pointers

- `apps/layer-gateway/src/models.rs` — `Blob` struct + `blobs` field
  on `UpsertDocument` / `DocumentResponse`.
- `apps/layer-gateway/src/clients/aerospike.rs` — extend
  `doc_to_bins()` / `bins_to_doc()` to handle `blob:{key}` and
  `blobct:{key}` bins via native `Value::Blob`. Reuse the byte path
  from `put_raw`/`get_raw`.
- `apps/layer-gateway/src/routes/upsert.rs` — accept blobs, validate
  size, write through.
- `apps/layer-gateway/src/routes/fetch.rs` — new
  `GET .../documents/{id}/blobs/{key}` handler returning
  `application/octet-stream` with ETag.
- `apps/layer-gateway/src/clients/turbopuffer.rs` (wherever the tpuf
  upsert is shaped) — explicitly drop the `blobs` field before
  writing.
- Tests: a round-trip test with a small fixture image, plus a
  size-limit reject test.

Happy to iterate on any of this. The two things we most want your
read on are (a) the aerospike-only field semantics, and (b) whether
the dedicated blob GET endpoint is the right read shape vs. inlining
behind an `include_blobs` flag.

Thanks —
adam (hev-shop)
