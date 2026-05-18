# hev-shop → layer-dashboard team: pipeline progress is hard to read

Hi —

I just ran a multi-hour review-embed backfill (v1 → v2-amazon-reviews
namespace migration, ~14k vectors written so far against ~700k pending)
and spent more time misreading the dashboard than I'd like. Filing
this as a punch list of UX gaps I hit, ranked by how much they cost me
in confusion or wasted clicks.

## TL;DR

| Gap                                                                | Why it tripped me                                                                                                                                                                  |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `failed_count` is shown without context                            | I had 8 stale docs I'd manually moved to `failed` for cleanup. Dashboard surfaced "8 failed" prominently; took me a minute to remember it wasn't a regression.                     |
| `indexed_rate_per_min` is smoothed over 5 min                      | After every GPU pod swap the rate falls and stays low for several minutes. Real instantaneous throughput is much higher. Hard to tell "the worker is healthy" from "it's stuck."   |
| Pipeline `indexed` count jumps in claim-batch chunks (~2000)       | Workers `upsert_vectors` continuously but only call `complete_pipeline_documents` at the end of each claim. So `indexed` looks frozen for minutes even while writes are flowing.   |
| No view of destination namespace row counts                        | The truth is in `v2-amazon-reviews-{0..15}/metadata.approx_row_count`. Had to curl all 16 shards in a loop and sum. The pipeline view should show "vectors landed" alongside docs. |
| Failed docs don't say why                                          | Once a doc lands in `failed`, the dashboard tells me nothing about the cause. I had to `kubectl logs` the worker pod and correlate timestamps.                                     |
| No worker-side health alongside pipeline state                     | OOMKills, image-pull failures, ephemeral-storage eviction — all invisible from the dashboard. I burned ~30 min chasing "pipeline stuck" when the real problem was kubelet evicting pods. |

## What would actually help

### 1. Distinguish "no work" from "stuck"

Right now `processing_count: 0` looks identical to `processing_count: 0 because the worker died`. Add a derived "worker-side liveness" signal — e.g. claim heartbeats per minute against the pipeline. If claims are flowing but `indexed` isn't moving, that's a meaningful state.

### 2. Show destination vector counts alongside pipeline counts

Each pipeline has a target namespace (`pipeline.target_namespace`, plus per-shard for the sharded review case). Showing `approx_row_count` from the namespace metadata next to the pipeline's `indexed` count would have answered "is the actual work happening?" in one screen instead of forcing me to curl 16 namespaces.

For the sharded case (`v2-amazon-reviews-{0..15}`), I'd want a roll-up: total rows across all shards belonging to a pipeline_id. If layer doesn't currently track the pipeline → namespace-shard relationship, the indexer client could attach a `pipeline_id` attribute on upsert so a metric can group them.

### 3. Surface instantaneous and windowed rates side-by-side

Show 1-min, 5-min, 30-min rate. Current 5-min average is the worst signal during scale-up / scale-down. A 1-min rate would have showed the GPU pod was actually fine ~60s after restart; the 5-min average lagged.

### 4. Failure reason on the failed docs

When a worker fails a doc, it sets stage=`failed` but the reason is in the worker's stdout. Could the worker also write a `failed_reason` attribute on the document chunk before marking failed? Then the dashboard could show a tooltip / column.

For our specific case the error was `json.decoder.JSONDecodeError` on a partial HF stream. Knowing that on the dashboard would have cut hours.

### 5. Worker-side panel: pods, recent restarts, OOMs, image-pull status

Even just a list of pods with their `RESTARTS` count, last termination reason (OOMKilled / ContainerStatusUnknown / Evicted), and image tag would be huge. I had to flip between `kubectl get pods`, `kubectl describe`, and the pipeline status in the dashboard to get a complete picture.

If that's out of scope for the layer-dashboard, at least link out to a known kubectl-ish view (k9s URL, lens, Datadog, whatever the team uses).

### 6. Stale `target_namespace` after pipeline reuse

Side note — when I bumped `reviews_namespace_base` from `amazon-reviews` to `v2-amazon-reviews`, the actual writes correctly went to `v2-amazon-reviews-*` (per-call namespace arg on `upsert_vectors`). But `GET /v2/pipelines` still shows `target_namespace: amazon-reviews` for `hev-shop-reviews`. The dashboard then displays the stale namespace. Either:

- expose a PATCH endpoint to update target_namespace on an existing pipeline (and have the dashboard sniff drift between pipeline.target_namespace and actual write namespace), or
- mark the field as "advisory" in the UI so it's not taken as ground truth

We hit this during the v2 migration and the dashboard's stale display added friction to the cutover decision.

## What we'd give up to get the above

Nothing critical from my side. We don't depend on the dashboard for control plane (we drive everything via API), so any of these are pure observability wins. Happy to provide the JSON shapes the indexer worker emits if it helps.

Thanks —
adam (hev-shop)
