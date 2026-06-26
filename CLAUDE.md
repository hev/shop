# hev-shop Claude Context

`hev-shop` is the product-search demo and production storefront for showing how
hev layer coordinates ingestion, product image embedding, product search,
recommendations, and freshness-aware reads. This file is for product, design,
research, and strategy context. For engineering and operations guidance, read
`AGENTS.md`.

## ⚠️ IMPORTANT — this repo is a Layer design-preview customer

This repo is a **design-preview customer of hev layer**, not part of the Layer
product. Its job is to *use* Layer the way a real customer would and **report
back** to the Layer team. That feedback loop is a primary responsibility of this
repo, not a side task — the demo working is table stakes; the signal we send the
Layer team is the deliverable.

**When you hit friction, do not fix Layer from here — report it:**

- **A bug, or docs that are wrong / unclear / missing** → file a **GitHub issue**
  on the Layer repo (`hev/layer`) with a minimal repro and the exact page or
  behavior at fault.
- **A missing feature or capability gap** → open an **RFC** in the Layer repo
  (`../layer/docs/rfcs/`), in the existing RFC shape, with this workload as the
  motivating / acceptance case.

**Operations are Layer's job.** This repo has operational access to the shared
Layer cluster, but the goal is that Layer operates *itself* — autoscaling,
scale-to-zero, scheduling, binpacking. Let it. Do **not** hand-tune what Layer is
meant to manage.

- When Layer falls short — autoscaling lags, a pipeline stalls, scale-to-zero
  misbehaves — it is OK to **intervene** to keep the demo healthy. But every
  intervention **must** produce a GitHub issue (bug) or an RFC (missing
  capability). An undocumented manual fix is a process failure: the intervention
  is the symptom, the report is the deliverable.
- **Shared namespace / binpacking.** This repo deploys to a namespace in the
  shared demo cluster alongside the other demos (shelf, shop, chart,
  hybrid-text-fusion-demo, label). Scheduling / binpacking contention may bite.
  Same rule: intervene to stay healthy if you must, but the result is a GH issue
  or an RFC documenting the shortfall — never a silent workaround.

The deliverable of any friction is always a **paper trail in `hev/layer`** (issue
or RFC) so the design-preview signal reaches the Layer team.

## Product Role

The storefront demonstrates a concrete buyer workflow over Amazon product data:
search products, inspect product detail, and browse visually similar products.
The interesting hev layer story is the clean pipeline lifecycle: product
metadata is staged as chunks, GPU workers claim pending docs, CLIP vectors are
written through Layer, and reads expose gateway perf/freshness signals.

## Design Intent

- Keep the UI useful as a storefront, not just a pipeline demo.
- Make visual similarity and semantic product search feel like product
  affordances.
- Treat operational status as supporting evidence for the pipeline story, not
  as the primary user experience.
- Preserve clear boundaries between storefront UX, indexer API contracts, and
  Layer pipeline mechanics.

## Strategic Notes

- `amazon-products` is the primary product namespace.
- CLIP image embeddings are the differentiating retrieval surface.
- The project should prove that Layer pipelines can support a simple,
  production-shaped extraction/embedding loop without an app-owned vector
  bookkeeping layer.
- Product docs should describe what users can do; operational commands belong
  in `AGENTS.md`.

## Pipeline Authoring

hev layer supports two equal authoring surfaces for pipelines: declarative
config (CRD/YAML) and SDK calls in app code. Shop uses both, split by what
each surface owns:

- Worker shape (image, compute pool, scaling) is declarative: the `Pipeline`
  resources under `indexer/pipelines/` are reconciled by the Layer operator,
  which owns the worker Deployments and KEDA scaling.
- Queue creation and the document lifecycle stay in SDK calls
  (`ensure_pipeline` in `indexer/app.py`, chunk/claim/vector calls in the
  stage scripts), because gateway state lives next to the code that uses it.

The SDK and YAML surfaces should round-trip through one schema. Drift between
what the SDK can express and what YAML can express is a Layer bug, not a shop
choice to work around.

App-owned Layer resources live next to the indexer code: `Pipeline` YAML under
`indexer/pipelines/`, `Function`/UDF YAML under `indexer/udfs/`. The Helm chart
owns the always-on API/web Deployments and their config injection, not Layer
pipeline or function shape.
