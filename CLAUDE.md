# CLAUDE.md

## Live endpoints

The app runs on EKS in namespace `hev-shop`, fronted by a shared ALB
(IngressGroup `hev-public`). Public DNS comes from `../mesh/infra/ingress/hev-shop/`.

| Surface          | URL                                       | Backed by Service                                     |
| ---------------- | ----------------------------------------- | ----------------------------------------------------- |
| Storefront       | https://hev-shop.com                      | `hev-shop-web` (port 80 → pod 3000)                   |
| Storefront (www) | https://www.hev-shop.com → 301 apex       | LBC `redirect-to-apex` action                         |
| Indexer API      | https://api.hev-shop.com                  | `hev-shop-api` (port 8080)                            |
| Layer gateway    | https://aws-us-east-1.hevlayer.com        | `layer-gateway` in namespace `layer` (port 8080)      |

The web pod talks to the API in-cluster via
`HEV_SHOP_API_BASE=http://hev-shop-api.hev-shop.svc.cluster.local:8080`
(see `helm/hev-shop/templates/web.yaml`). Use the public URL above when
calling from your laptop.

### Curl the live API directly

```sh
curl -s https://api.hev-shop.com/healthz
curl -s https://api.hev-shop.com/meta | jq .
curl -s "https://api.hev-shop.com/product/B00FI7TCGI" | jq .
curl -s -X POST -H 'content-type: application/json' \
  -d '{"query":"wireless headphones","top_k":3}' \
  https://api.hev-shop.com/search | jq .
curl -s "https://api.hev-shop.com/search/reviews?asin=B00FI7TCGI&q=battery&top_k=4" | jq .
```

The full request/response contract for these endpoints is in
`indexer/app/main.py` and mirrored on the web side in `web/lib/backend.ts`.

### Curl the layer gateway directly

```sh
curl -s https://aws-us-east-1.hevlayer.com/v2/pipelines | jq .
curl -s https://aws-us-east-1.hevlayer.com/v2/namespaces/amazon-products/metadata | jq .
```

### Reach in-cluster from your laptop

Use port-forward only when bypassing the ALB is necessary (e.g. testing
a service that doesn't have public DNS — both `hev-shop-api` and
`layer-gateway` *do* have public DNS, see the table above):

```sh
kubectl port-forward -n hev-shop  svc/hev-shop-api  18080:8080
kubectl port-forward -n layer     svc/layer-gateway 18180:8080
curl -s http://127.0.0.1:18080/meta
curl -s http://127.0.0.1:18180/v2/namespaces/amazon-products/metadata
```

### Pod and log access

```sh
kubectl get pods    -n hev-shop
kubectl logs        -n hev-shop deploy/hev-shop-api     --tail=200
kubectl logs        -n hev-shop deploy/hev-shop-web     --tail=200
kubectl exec -it    -n hev-shop deploy/hev-shop-api -- sh
```

The Go CLI takes two URL flags: `--gateway-url` points at layer-gateway,
`--indexer-url` points at the hev-shop indexer API. Both have public DNS:

```sh
go run . status --indexer-url https://api.hev-shop.com --pipeline-id hev-shop-product-images
go run . health --gateway-url https://aws-us-east-1.hevlayer.com
```

## Indexer module layout (`indexer/app/`)

| file              | what's in it                                                              |
| ----------------- | ------------------------------------------------------------------------- |
| `main.py`         | FastAPI app — `/search`, `/product/{asin}`, `/meta`, `/index`, `/backfill` |
| `worker.py`       | Process entrypoint. Reads `WORKER_TYPE` env, dispatches to a stage        |
| `pipeline.py`     | **The N-stage pipeline.** `STAGES` dict + `run_stage` driver + `process_*` |
| `extraction.py`   | CPU worker — drains the Layer extraction pipeline, stages products + raw reviews |
| `embedders.py`    | `CLIPImageEmbedder`, `CLIPTextEmbedder`, `QwenTextEmbedder` model wrappers |
| `classifier.py`   | OpenRouter client for review tag classification                           |
| `layer_client.py` | HTTP client for `layer-gateway`                                           |
| `jobs.py`         | Extraction/backfill job document shape for the Layer pipeline             |
| `dataset.py`      | HuggingFace `McAuley-Lab/Amazon-Reviews-2023` reader                      |
| `records.py`      | Internal data shapes — `ProductRecord`, `ReviewRecord`, vector attrs, review-pipeline plumbing |
| `models.py`       | Pydantic HTTP request/response contracts (API boundary only)              |
| `config.py`       | `pydantic_settings.BaseSettings` — env-var-driven config                  |

### The layer N-stage pipeline

`pipeline.py:STAGES` is a dict — one entry per stage. The driver
`_run_once(stage, ctx)` owns the claim/heartbeat/release lifecycle;
each stage's `process_*` function returns a `StageOutcome(complete=,
fail=, release=)` listing per-doc dispositions.

```
extract:          (Layer extraction pipeline) → stages products + raw reviews
embed-products:   pending  → indexed   (CLIP image vectors)
embed-reviews:    pending  → indexed   (Qwen text vectors, chunked, prefix=review-embed:)
classify-reviews: pending  → indexed   (OpenRouter tags, prefix=review-classify:)
                                       — fans out ASINs to the aggregate pipeline
aggregate-tags:   pending  → indexed   (review scan → PATCH product rows)
```

`WORKER_TYPE` env values map to `STAGES` keys via `worker.STAGE_FOR_WORKER_TYPE`
(`gpu`→`embed-products`, `review-embed`→`embed-reviews`, etc). `cpu` runs
`ExtractionWorker` instead because it expands extraction jobs into product and
review work items.

To add a new stage:
1. Write `process_yourstage(ctx, doc_ids) -> StageOutcome` in `pipeline.py`
2. Add an entry to `STAGES` with the `pipeline_attr` / `from_stage` /
   `claim_size_attr` / optional `prefix` and `setup`
3. Map a `WORKER_TYPE` value to it in `worker.STAGE_FOR_WORKER_TYPE`
4. Add a test in `tests/test_pipeline.py`

### Running the tests

```sh
cd indexer
python3 -m pytest tests/ --tb=short
```

43 tests; pure helpers + STAGES manifest + driver behavior + per-stage
contracts against fake LayerClient/embedders/classifier in
`tests/_fakes.py`.
