# hev-shop -> Layer 0.1 launch-ready plan

## Context

`hev-shop` is the canonical consumer that proves Layer's pipeline and
operational features end to end. Today it leans on a subset: all pipeline
queues are SDK-created, products do not carry an app-owned catalog run marker,
searches show only a page-local count, and several distinctive Layer surfaces
(config-declared pipelines, namespace snapshots/history, search-history) are not
yet visible in the storefront.

The goal is still six workstreams: make shop exercise more of Layer while
staying simple, and ship a polished storefront for the 0.1 launch. The spikes
below changed the implementation details for pipelines, drops, and recent
searches.

---

## Spike results (2026-05-30)

### 1. Recency / drops contract

**Result:** do not implement shop filters directly over
`_hevlayer_upserted_at` for 0.1.

Evidence:
- Layer stamps `_hevlayer_upserted_at` on writes, but Layer docs say caller
  filters should not send that field; the gateway owns the hidden consistency
  predicate.
- Gateway query code only injects `_hevlayer_upserted_at <= watermark` while
  the namespace is currently `Updating`; it reports `stable_as_of` on responses,
  but that is not the same as every query being pinned to that watermark.
- Layer docs list arbitrary temporal `as_of` queries as later roadmap work, and
  snapshots explicitly do not support arbitrary `as_of` in 0.1.
- Namespace history is facet snapshot history, not an ingest-run ledger. Auto
  snapshots are content-deduped, so a nightly reindex of the same products can
  produce no new history entry if configured facet histograms are unchanged.

**Plan adjustment:** use an app-owned `catalog_run_id` / `catalog_run_started_at_ms`
on product vectors for launch drops. Use Layer snapshots/history to materialize
and display completed run markers, but do not depend on caller-visible reserved
timestamp filtering.

### 2. Pipeline CRD contract

**Result:** do not move the existing extraction queue to a Pipeline CRD until the
Layer operator path is made compatible with shop's current ownership model.

Evidence:
- The gateway queue API still creates a pipeline with
  `{id, target_namespace, distance_metric}`.
- The current `Pipeline` CRD is an operator-owned worker-deployment surface:
  `spec.worker` and `spec.scaling` are required by the docs/schema, and the
  operator creates a `{pipeline}-worker` Deployment.
- The operator does not currently register the gateway queue from the CRD. If
  shop removes runtime `ensure_pipeline`, staging extraction documents can 404.
- Applying a shop Pipeline CRD today would also risk a second extraction worker
  deployment next to the existing Helm-managed CPU worker.

**Plan adjustment:** keep runtime `ensure_pipeline` for all queues in 0.1.
Finish ID cleanup and document the intended split, but gate the actual CRD move
on either queue-only Pipeline CRD support or a deliberate migration of the CPU
worker deployment to operator ownership.

### 3. Nightly trigger / idempotency

**Result:** a bare CronJob that POSTs `/index` is not idempotent enough.

Evidence:
- `/index` builds extraction job IDs with UUIDs, so duplicate CronJob attempts
  enqueue duplicate work.
- The dataset slice is deterministic by category, offset, and count. Reindexing
  the same launch slice every night is a "catalog refresh" unless we explicitly
  rotate/select net-new rows.

**Plan adjustment:** add an explicit `run_id` to `/index`, make extraction job
IDs deterministic for `(run_id, category, offset, limit)`, and put that `run_id`
on product vectors. Configure the CronJob with `concurrencyPolicy: Forbid` and
pass a stable daily run ID.

### 4. Recent searches

**Result:** use Layer's `raw_query` support, not `q:` tags.

Evidence:
- The gateway records `raw_query` from `x-hevlayer-search-query`.
- `x-hevlayer-tag` / `x-hevlayer-tags` are still useful for segmentation, but
  query text does not need to be encoded into tags.

**Plan adjustment:** inject `x-hevlayer-search-query: <human query>` on the
gateway query call and read `raw_query` from `/search-history`.

---

## Updated launch decisions

- **Pipelines:** 0.1 keeps all gateway queues runtime-created through the SDK.
  Clean up duplicated IDs and document the desired future CRD split, but do not
  move extraction to a Pipeline CRD until the Layer operator can either register
  queue-only specs or own the existing CPU worker deployment.
- **Drops:** use shop-owned `catalog_run_id` and `catalog_run_started_at_ms`;
  do not filter on or expose `_hevlayer_upserted_at` from shop APIs.
- **Nightly trigger:** Kubernetes CronJob in the chart, but it must pass a
  deterministic `run_id` and avoid overlapping runs.
- **Recent searches:** consume Layer search-history; capture query text through
  `x-hevlayer-search-query` and use tags only for low-cardinality labels such as
  `surface:storefront`.

---

## Workstream 1 - Pipeline cleanup, with CRD migration gated

**Why:** CLAUDE.md says shop should keep Layer's SDK-vs-config contract honest,
but the current Pipeline CRD is not a safe drop-in replacement for shop's
existing extraction queue. We can still remove drift and make the future split
explicit without creating duplicate workers.

**0.1 changes**
1. **Single source of truth for IDs.** Keep the four pipeline IDs in Helm values
   and inject them through env vars; keep `config.py` defaults aligned for local
   dev. Add a focused test that the defaults match the chart values.
2. **Keep runtime queue registration.** Leave `ensure_pipeline` calls in
   `indexer/app/main.py`, `indexer/app/worker.py`, `indexer/app/extraction.py`,
   and `indexer/app/pipeline.py`.
3. **Document the gated CRD path.** Update `AGENTS.md` and `CLAUDE.md` with:
   - current 0.1 state: gateway queues are SDK-created;
   - future target: extraction can become config-declared once the CRD path
     either registers the gateway queue or owns the shop CPU worker;
   - stage -> WORKER_TYPE -> deploy map.

**Not in 0.1 unless Layer changes first**
- Do not add `helm/hev-shop/pipelines/extraction.yaml` as an active resource.
- Do not remove extraction `ensure_pipeline`.

**Files:** `helm/hev-shop/values.yaml`, `common/hev_shop_common/config.py`,
`common/tests/test_config.py`, `indexer/app/*` only if comments/tests need
updating, `AGENTS.md`, `CLAUDE.md`.

---

## Workstream 2 - Catalog run marker and drop filter primitive

**Why:** Launch drops need a caller-owned field that shop can filter on safely.
Layer's reserved timestamp remains useful internally, but shop should not build
public API behavior around caller filters on `_hevlayer_upserted_at`.

**Changes**
1. **Add run metadata to `/index`.** Add optional `run_id` and
   `run_started_at_ms` to `IndexRequest`. If omitted, generate a run ID for
   ad-hoc runs; the CronJob will pass a deterministic daily ID such as
   `catalog-2026-05-30`.
2. **Make extraction job IDs idempotent.** For index jobs, derive document IDs
   from `(run_id, category, row_offset, row_limit, pipeline_id, namespace)`
   instead of UUIDs. Backfills can keep UUIDs unless we explicitly add
   backfill idempotency later.
3. **Stamp product vectors with run metadata.** Add `catalog_run_id` and
   `catalog_run_started_at_ms` to product vector attributes when product rows
   are upserted. Keep these app-owned names; do not write `_hevlayer_*`.
4. **Expose filter support.** Add `catalog_run_id` to `SearchRequest` and
   translate it to `["catalog_run_id", "Eq", run_id]`, composing with existing
   category/tag filters. Include the run fields in search attributes so cards
   can show "catalog refresh <date>" when appropriate.
5. **CLI parity.** Add `--catalog-run-id` to `shop search` after OpenAPI/codegen.
6. **Tests.** Cover idempotent job ID generation, product attributes, and search
   filter composition.

**Files:** `indexer/app/models.py`, `indexer/app/jobs.py`,
`indexer/app/extraction.py`, `common/hev_shop_common/records.py`,
`common/tests/`, `indexer/tests/`, `search/app/models.py`,
`search/app/main.py`, `search/tests/test_search.py`, `search/openapi.json`,
`client/searchapi`, `cmd/search.go`, `web/lib/backend.ts`.

---

## Workstream 3 - Result count + pagination ("X-Y of Z")

**Why:** `SearchResponse` already returns optional `count` and `next_cursor`.
The web gap is presentation and state retention across cursor pages.

**Changes**
1. In `web/app/search/page.tsx`, track `offset` in the URL alongside `cursor`.
   Render `Showing {offset+1}-{offset+results.length} of {bounded ? ">= " : ""}{count}`.
2. Either carry the page-1 count forward in URL params or request `with_count`
   on cursor pages. Prefer carrying the count only if the URL stays clean enough;
   otherwise accept the extra count round-trip for correctness.
3. Mirror the count/window line on review search results.
4. No API shape change unless a tiny frontend helper is useful.

**Files:** `web/app/search/page.tsx`, review-search render path,
`web/lib/backend.ts` only if helper types are needed.

---

## Workstream 4 - Nightly catalog drops

**Why:** The storefront should show completed catalog refreshes and let users
filter products from a specific run. The completed signal should come from
Layer-observed indexed state, but the run identity should be shop-owned.

**Changes**
1. **Nightly reindex CronJob.** Add
   `helm/hev-shop/templates/cronjob-nightly-index.yaml` that POSTs `/index`
   in-cluster with:
   - category/count/job_size from chart values;
   - `run_id=catalog-$(date -u +%Y-%m-%d)`;
   - `concurrencyPolicy: Forbid`;
   - sane `activeDeadlineSeconds`, backoff, and history limits.
2. **Drop discovery endpoint.** Add `GET /drops` in the search service. It
   should materialize/read a Layer field snapshot for `catalog_run_id` and return
   recent runs with `{run_id, product_count, stable_as_of}`. Configure
   `catalog_run_id` as a Layer facet field for `amazon-products` if we want this
   to be cheap through stored snapshots; otherwise use an on-demand origin
   snapshot with caching similar to `/meta`.
3. **UI.** Add a "Drops" / "What's new" surface that lists recent
   `catalog_run_id` values. Selecting a drop searches with `catalog_run_id`.
4. **CLI parity.** Add `shop drops`.
5. **Ingress.** Add `/drops` to the search-service path routing under
   `../layer/infra/ingress/hev-shop/`.
6. **Nightly workflow check.** Keep `.github/workflows/nightly.yml` read-only.
   After the CronJob window, assert that `/drops` contains the expected recent
   daily run ID and nonzero count. Do not assert that namespace history advanced
   unless the run marker facet is configured and expected to change.

**Files:** `helm/hev-shop/templates/cronjob-nightly-index.yaml` (new),
`helm/hev-shop/values.yaml`, `search/app/main.py`, `search/app/models.py`,
`search/openapi.json`, `client/searchapi`, `cmd/`, `web/`,
`.github/workflows/nightly.yml`, `../layer/infra/ingress/hev-shop/`.

**Open product decision:** if "drop" must mean net-new products rather than
"the refreshed launch corpus for this date", define a row selection policy
(e.g. rotating offset window or increasing count) before implementing the
CronJob. The current dataset reader returns a deterministic slice for a fixed
category/count.

---

## Workstream 5 - Recent searches (Layer search-history)

**Why:** Surface "what people are searching" using Layer search-history directly
without building a shop-owned event store.

**Changes**
1. **Tag the raw query correctly.** In `/search`, set
   `x-hevlayer-search-query: <query text>` on the gateway query request. Because
   the Python SDK does not expose per-call headers, inject it with an httpx
   request hook that reads a request-local `contextvar`. Optionally add
   `x-hevlayer-tags: surface:storefront`.
2. **Read endpoint.** Add `GET /search/recent` to the search service. It calls
   `GET /v2/namespaces/{ns}/search-history?limit=N`, extracts `raw_query`,
   normalizes whitespace/case, drops empty or overlong values, dedupes
   newest-first, and returns the last N distinct strings.
3. **UI element.** Render a restrained "Recent searches" affordance near the
   search bar or homepage, with chips linking to `/search?q=...`.
4. **CLI parity.** Add `shop recent-searches`.
5. **Ingress.** `/search` is already routed by prefix, so no new ALB rule is
   needed for `/search/recent`.

**Files:** `search/app/main.py`, `search/app/models.py`,
`search/tests/_fakes.py`, `search/tests/test_search.py`, `search/openapi.json`,
`client/searchapi`, `cmd/`, `web/components/Header.tsx` or `web/app/page.tsx`.

---

## Workstream 6 - Branding & hevmind linking

**Why:** Make shop more on-brand and create a clear funnel back to hevmind.com
("hire the people who built this site").

**Changes**
1. Wire the footer "Hire the people who made this" link
   (`web/components/Footer.tsx`, currently `href="#"`) to `https://hevmind.com`.
2. Light copy polish on the landing hero and header announcement. Keep the
   existing witty register, add a clear "built by hevmind" tie-in, and avoid
   turning the storefront into a marketing page.
3. Optional: add a small mono treatment for technical labels if it matches the
   existing visual system.

**Files:** `web/components/Footer.tsx`, `web/app/page.tsx`,
`web/components/Header.tsx`, `web/tailwind.config.ts` only if adding a font.

---

## Sequencing

Suggested implementation order:

1. **WS1 safe cleanup** - ID drift tests and docs. Do not touch CRD runtime yet.
2. **WS2 catalog run primitive** - `run_id`, deterministic job IDs, product
   attributes, and search filter support.
3. **WS4 nightly drops** - CronJob, `/drops`, UI, CLI, ingress, nightly check.
4. **WS3 pagination** - frontend-only, can run in parallel after WS2 if desired.
5. **WS5 recent searches** - independent of drops, but touches search OpenAPI and
   CLI like WS4; coordinate codegen.
6. **WS6 branding** - low-risk UI copy/link pass.

Operationally, run one clean-slate launch reindex after WS2 lands so all product
rows have `catalog_run_id`. The runbook should delete/rebuild the product and
review namespaces only when explicitly scheduled; do not fold that destructive
step into app code.

---

## Verification

- **Per-service tests** for touched areas:
  `cd common && python3 -m pytest tests/ --tb=short`,
  `cd search && python3 -m pytest tests/ --tb=short`,
  `cd indexer && python3 -m pytest tests/ --tb=short`.
- **OpenAPI drift:** `make openapi && make codegen`; route/model changes must
  leave `search/openapi.json`, `indexer/openapi.json`, and generated clients in
  sync.
- **Run marker:** call `/index` twice with the same small `run_id`; confirm the
  extraction queue does not duplicate job IDs and product search results include
  `catalog_run_id`.
- **Drops:** trigger the CronJob manually with a test run ID; after workers drain
  and the namespace is stable, `GET /drops` returns that run ID with a nonzero
  product count, and searching with `catalog_run_id` returns only that run.
- **Pagination:** load `/search?q=...`, page forward with the gateway cursor,
  and confirm the displayed window advances correctly.
- **Recent searches:** issue several searches, then `GET /search/recent`; confirm
  returned queries match `raw_query` in Layer search-history and are deduped.
- **Pipeline cleanup:** verify existing `ensure_pipeline` paths still create all
  four queues and `shop status` works for product and extraction pipelines.
- **Branding:** visual check of the footer link and copy in the running web app.

