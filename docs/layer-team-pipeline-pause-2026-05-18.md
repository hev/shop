# hev-shop → layer team: pipeline pause/resume primitive

Hi —

While running a multi-hour review-embed backfill on hev-shop today I
wanted a clean way to stop work without scaling deployments and without
losing in-flight progress. The current options are all clunky:

- `kubectl annotate scaledobject ... paused-replicas=0` — pauses
  consumers but workers' active claims keep running until lease expires
  (15 min default), and there's no signal that says "don't claim more."
- Manual `UPDATE pipeline_documents SET stage='pending' …` to release
  zombie claims — fine for cleanup, terrible as a control-plane.
- Scale deployments to 0 — KEDA fights you on the next polling cycle.

What I actually want is a layer-gateway-side switch on a pipeline that
says "stop handing out claims" without touching the consumer side at
all. Filing this so the team can evaluate.

## Proposed API

```
POST   /v2/pipelines/{pipeline_id}/pause     → 204 No Content
POST   /v2/pipelines/{pipeline_id}/resume    → 204 No Content
GET    /v2/pipelines/{pipeline_id}           → existing response gains `paused: bool`
```

Optional body on POST /pause:

```json
{
  "reason": "ops: pausing review backfill for v3 cutover",
  "paused_by": "adam@hev"
}
```

Stored on the `pipelines` row alongside the existing fields. Surfaces
in /v2/pipelines list responses too so dashboards can show a paused
indicator.

## Claim semantics when paused

`POST /v2/pipelines/{pipeline_id}/claim` short-circuits and returns an
empty list while `paused=true`. Same shape as when there's no pending
work — that's already the well-behaved case for consumers (they sleep
`worker_poll_seconds` and try again). No consumer-side change required.

Heartbeat and complete still work — in-flight claims that the consumer
already holds get to finish. That avoids data loss when an operator
hits pause mid-batch. Lease-expiry rules unchanged.

## Two behaviors I want to be explicit about

1. **No automatic claim release on pause.** If an operator wants to
   stop in-flight work *now*, they can call the existing
   `documents/stage` endpoint with `stage=pending, from_stage=embedding`
   to release. Pause is "stop giving out new work," not "kill in-flight."

2. **Backfill/extraction stays usable.** Staging new documents into a
   paused pipeline should still succeed (writers keep writing, consumers
   just don't pick up). Otherwise pause becomes a bigger hammer than it
   needs to be — we'd lose the ability to queue up work for a planned
   maintenance window.

## Implementation pointers

`apps/layer-gateway/src/routes/pipeline.rs` — drop two route handlers
plus a `paused` column on the `pipelines` table. The `claim_documents`
handler does a single read of the pipeline row (or a tiny in-memory
cache; pause state changes are rare) and bails before the SQL claim
update if paused. A bool gate is fine; if you want graceful pause
windows later you can extend the body to take a `paused_until`
timestamp without breaking the API shape.

## Why not consumer-side

I considered adding `POST /backfill/pause` on the indexer service. It
works for our case but doesn't generalize — every consumer of a layer
pipeline would have to add its own pause primitive. Layer's the right
place since it already owns the claim contract.

## Operationally useful adjacencies (out of scope for the first cut)

- A `paused_at` column for audit ("when did this go down?"). Same row.
- A `paused_reason` shown in the dashboard list — pairs nicely with
  the dashboard punch list I filed in `docs/dashboard-team-note-2026-05-18.md`.
- A *single* `POST /v2/pipelines/pause-all?prefix=hev-shop-` for the
  case where you want to pause all of a customer's pipelines in one
  call (e.g., before a maintenance push). Not urgent.

Happy to take feedback on the API shape — I'd rather get it right
once than chase changes later.

Thanks —
adam (hev-shop)
