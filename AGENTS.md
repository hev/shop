# hev-shop Agent Guide

This file is for engineering and operations work in `hev-shop`. For product,
design, and strategic context, read `CLAUDE.md`.

## Live Endpoints

The app runs on EKS in namespace `hev-shop`, fronted by a shared ALB
(IngressGroup `hev-public`). Public DNS comes from
`../layer/infra/ingress/hev-shop/`.

| Surface | URL | Backed by Service |
|---|---|---|
| Storefront | https://hev-shop.com | `hev-shop-web` (port 80 to pod 3000) |
| Storefront (www) | https://www.hev-shop.com redirects to apex | LBC `redirect-to-apex` action |
| Indexer API | https://api.hev-shop.com | `hev-shop-api` (port 8080) |
| Layer gateway | https://aws-us-east-1.hevlayer.com | `layer-gateway` in namespace `layer` (port 8080) |

The web pod talks to the API in-cluster via
`HEV_SHOP_API_BASE=http://hev-shop-api.hev-shop.svc.cluster.local:8080`
(see `helm/hev-shop/templates/web.yaml`). Use the public URL above when
calling from a laptop.

## Curl Checks

```sh
curl -s https://api.hev-shop.com/healthz
curl -s https://api.hev-shop.com/meta | jq .
curl -s "https://api.hev-shop.com/product/B00FI7TCGI" | jq .
curl -s -X POST -H 'content-type: application/json' \
  -d '{"query":"wireless headphones","top_k":3}' \
  https://api.hev-shop.com/search | jq .
curl -s "https://api.hev-shop.com/search/reviews?asin=B00FI7TCGI&q=battery&top_k=4" | jq .
```

The full request/response contract is in `indexer/app/main.py` and mirrored on
the web side in `web/lib/backend.ts`.

Layer gateway checks:

```sh
curl -s https://aws-us-east-1.hevlayer.com/v2/pipelines | jq .
curl -s https://aws-us-east-1.hevlayer.com/v2/namespaces/amazon-products/metadata | jq .
```

## Cluster Access

Use port-forward only when bypassing the ALB is necessary:

```sh
kubectl port-forward -n hev-shop  svc/hev-shop-api  18080:8080
kubectl port-forward -n layer     svc/layer-gateway 18180:8080
curl -s http://127.0.0.1:18080/meta
curl -s http://127.0.0.1:18180/v2/namespaces/amazon-products/metadata
```

Pod and log access:

```sh
kubectl get pods -n hev-shop
kubectl logs     -n hev-shop deploy/hev-shop-api --tail=200
kubectl logs     -n hev-shop deploy/hev-shop-web --tail=200
kubectl exec -it -n hev-shop deploy/hev-shop-api -- sh
```

The Go CLI takes two URL flags: `--gateway-url` points at layer-gateway,
`--indexer-url` points at the hev-shop indexer API.

```sh
go run . status --indexer-url https://api.hev-shop.com --pipeline-id hev-shop-product-images
go run . health --gateway-url https://aws-us-east-1.hevlayer.com
```

## Indexer Layout

`indexer/app/`:

| File | Purpose |
|---|---|
| `main.py` | FastAPI app: `/search`, `/product/{asin}`, `/meta`, `/index`, `/backfill` |
| `worker.py` | Process entrypoint; reads `WORKER_TYPE` and dispatches to a stage |
| `pipeline.py` | N-stage pipeline manifest and driver |
| `extraction.py` | CPU worker for extraction jobs, product staging, and raw review staging |
| `embedders.py` | `CLIPImageEmbedder`, `CLIPTextEmbedder`, `QwenTextEmbedder` wrappers |
| `classifier.py` | OpenRouter client for review tag classification |
| `jobs.py` | Extraction/backfill job document shapes |
| `dataset.py` | HuggingFace `McAuley-Lab/Amazon-Reviews-2023` reader |
| `records.py` | Internal product/review data shapes and vector attrs |
| `models.py` | Pydantic HTTP request/response contracts |
| `config.py` | `pydantic_settings.BaseSettings` env-var config |

## Pipeline Model

`pipeline.py:STAGES` is a dict with one entry per stage. `_run_once(stage,
ctx)` owns claim, heartbeat, release, and per-doc disposition handling. Each
stage processor returns a `StageOutcome(complete=, fail=, release=)`.

```text
extract:          Layer extraction pipeline -> products + raw reviews
embed-products:   pending -> indexed   (CLIP image vectors)
embed-reviews:    pending -> indexed   (Qwen text vectors, prefix=review-embed:)
classify-reviews: pending -> indexed   (OpenRouter tags, prefix=review-classify:)
aggregate-tags:   pending -> indexed   (review scan -> PATCH product rows)
```

`WORKER_TYPE` values map to `STAGES` keys via `worker.STAGE_FOR_WORKER_TYPE`.
`cpu` runs `ExtractionWorker` because it expands extraction jobs into product
and review work items.

To add a stage:

1. Write `process_yourstage(ctx, doc_ids) -> StageOutcome` in `pipeline.py`.
2. Add a `STAGES` entry with `pipeline_attr`, `from_stage`, `claim_size_attr`,
   optional `prefix`, and optional `setup`.
3. Map a `WORKER_TYPE` value to it in `worker.STAGE_FOR_WORKER_TYPE`.
4. Add focused tests in `tests/test_pipeline.py`.

## Tests

```sh
cd indexer
python3 -m pytest tests/ --tb=short
```

The test suite covers pure helpers, the `STAGES` manifest, driver behavior, and
per-stage contracts against fakes in `tests/_fakes.py`.

## Agent Rules

- Prefer public DNS for laptop checks unless the task specifically needs an
  in-cluster bypass.
- Keep the `indexer/app/` module boundary intact; avoid moving pipeline logic
  into API models or web code.
- Run the narrowest meaningful tests for code changes, or explain why they
  were not run.
- Do not revert unrelated user changes.
