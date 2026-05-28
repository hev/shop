# hev-shop Agent Guide

This file is for engineering and operations work in `hev-shop`. For product,
design, and strategic context, read `CLAUDE.md`.

## Repo Layout

Three Python services + one Next.js app, organized so each can be forked
independently:

```
hev-shop/
  search/                 # read API: /search, /product, /meta, /reviews/...
    app/{main,models}.py
    tests/                # pytest, see search/conftest.py
    Dockerfile, requirements.txt
  indexer/                # control plane + workers
    app/                  # /index, /backfill, /status + pipeline stages
    tests/                # pytest, see indexer/conftest.py
    Dockerfile, requirements.txt
  common/                 # shared library — Settings, records, embedders
    hev_shop_common/{config,records,embedders}.py
    tests/                # pytest, see common/conftest.py
    pyproject.toml
  web/                    # Next.js storefront
  helm/hev-shop/          # one chart, four deploys (search, indexer-api, web, workers)
```

Search and indexer both pull `hev_shop_common` via `pip install -e ../common`
(see each `requirements.txt`). The same pattern is used for the hevlayer SDK
in `../../layer/clients/python`.

## Live Endpoints

The app runs on EKS in namespace `hev-shop`, fronted by a shared ALB
(IngressGroup `hev-public`). Public DNS comes from
`../layer/infra/ingress/hev-shop/`.

| Surface | URL | Backed by Service |
|---|---|---|
| Storefront | https://hev-shop.com | `hev-shop-web` (port 80 to pod 3000) |
| Storefront (www) | https://www.hev-shop.com redirects to apex | LBC `redirect-to-apex` action |
| Read API | https://api.hev-shop.com/{search,product,meta,...} | `hev-shop-search` (port 8080) |
| Indexer API | https://api.hev-shop.com/{index,backfill,status} | `hev-shop-indexer-api` (port 8080) |
| Layer gateway | https://aws-us-east-1.hevlayer.com | `layer-gateway` in namespace `layer` (port 8080) |

`api.hev-shop.com` is path-routed by the ALB: `/search*`, `/product*`,
`/meta*`, and `/reviews/*` go to `hev-shop-search`; `/index`, `/backfill`,
`/status` go to `hev-shop-indexer-api`. Update the ingress under
`../layer/infra/ingress/hev-shop/` when adding new routes.

The web pod only calls read endpoints, so it talks to search in-cluster:
`HEV_SHOP_API_BASE=http://hev-shop-search.hev-shop.svc.cluster.local:8080`
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

# Indexer control plane
curl -s "https://api.hev-shop.com/status?pipeline_id=hev-shop-product-images" | jq .
```

The read-API request/response contract is in `search/app/main.py` (mirrored
on the storefront in `web/lib/backend.ts`); the indexer control-plane
contract is in `indexer/app/main.py`.

Layer gateway checks:

```sh
curl -s https://aws-us-east-1.hevlayer.com/v2/pipelines | jq .
curl -s https://aws-us-east-1.hevlayer.com/v2/namespaces/amazon-products/metadata | jq .
```

## Cluster Access

Use port-forward only when bypassing the ALB is necessary:

```sh
kubectl port-forward -n hev-shop  svc/hev-shop-search        18080:8080
kubectl port-forward -n hev-shop  svc/hev-shop-indexer-api   18081:8080
kubectl port-forward -n layer     svc/layer-gateway          18180:8080
curl -s http://127.0.0.1:18080/meta
curl -s http://127.0.0.1:18081/status
curl -s http://127.0.0.1:18180/v2/namespaces/amazon-products/metadata
```

Pod and log access:

```sh
kubectl get pods -n hev-shop
kubectl logs     -n hev-shop deploy/hev-shop-search       --tail=200
kubectl logs     -n hev-shop deploy/hev-shop-indexer-api  --tail=200
kubectl logs     -n hev-shop deploy/hev-shop-web          --tail=200
kubectl exec -it -n hev-shop deploy/hev-shop-search -- sh
```

## `shop` CLI

Every hev-shop endpoint has a matching subcommand. The binary is `shop`
(installable with `go install github.com/hev/shop@latest`).

| Command | Endpoint |
|---|---|
| `shop search "wireless headphones" --top-k 3` | `POST /search` |
| `shop recommend B00FI7TCGI --top-k 3` | `POST /recommend` |
| `shop product B00FI7TCGI` | `GET /product/{asin}` |
| `shop meta` | `GET /meta` |
| `shop search-reviews --asin B00FI7TCGI --query battery` | `GET /search/reviews` |
| `shop review-samples --asin B00FI7TCGI --ids r1,r2` | `GET /reviews/samples` |
| `shop index --category Electronics --count 1000` | `POST /index` |
| `shop backfill --category Electronics --asins B0001,B0002` | `POST /backfill` |
| `shop status --pipeline-id hev-shop-product-images` | `GET /status` |
| `shop health` | search `/healthz` + indexer `/status` |

The CLI talks to one host by default: `--api-base` (env `SHOP_API_BASE`,
default `https://api.hev-shop.com`). For port-forward dev, override
either service with `--search-url` / `--indexer-url`:

```sh
shop --search-url http://127.0.0.1:18080 meta
shop --indexer-url http://127.0.0.1:18081 status
```

## OpenAPI Specs

The committed specs at `search/openapi.json` and `indexer/openapi.json`
are the source of truth for the Go client. Regenerate after touching a
route or Pydantic model:

```sh
make openapi    # dumps both specs deterministically
make codegen    # regenerates client/searchapi + client/indexerapi
```

`tests/test_openapi_spec.py` in each service fails CI-like checks if the
committed spec drifts from the FastAPI app.

## Search Service Layout

`search/app/`:

| File | Purpose |
|---|---|
| `main.py` | FastAPI app: `/search`, `/search/reviews`, `/product/{asin}`, `/meta`, `/reviews/samples`, `/healthz` |
| `models.py` | Pydantic HTTP contracts for the read API |

Heavy lifting (Settings, embedder wrappers, namespace helpers) is in
`hev_shop_common`. The search pod loads `CLIPTextEmbedder` at boot to
embed query strings; review search uses `QwenTextEmbedder` and is gated
behind `API_REVIEW_SEARCH_ENABLED` (off by default — Qwen-8B needs a GPU).

## Indexer Service Layout

`indexer/app/`:

| File | Purpose |
|---|---|
| `main.py` | FastAPI control plane: `/index`, `/backfill`, `/status`, `/healthz` |
| `worker.py` | Process entrypoint; reads `WORKER_TYPE` and dispatches to a stage |
| `pipeline.py` | N-stage pipeline manifest and driver |
| `extraction.py` | CPU worker for extraction jobs, product staging, and raw review staging |
| `classifier.py` | OpenRouter client for review tag classification |
| `jobs.py` | Extraction/backfill job document shapes |
| `dataset.py` | HuggingFace `McAuley-Lab/Amazon-Reviews-2023` reader |
| `models.py` | Pydantic HTTP contracts for /index, /backfill, /status |

## Common Library

`common/hev_shop_common/`:

| File | Purpose |
|---|---|
| `config.py` | `pydantic_settings.BaseSettings` env-var config used by both services |
| `records.py` | `ProductRecord` / `ReviewRecord`, namespace + shard helpers, input normalizers, review-tag enum |
| `embedders.py` | `CLIPImageEmbedder`, `CLIPTextEmbedder`, `QwenTextEmbedder` lazy-init wrappers |

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
4. Add focused tests in `indexer/tests/test_pipeline.py`.

## Tests

Each service has its own pytest tree. Run the narrowest meaningful one for
the code you touched:

```sh
cd common  && python3 -m pytest tests/ --tb=short   # Settings + records
cd search  && python3 -m pytest tests/ --tb=short   # /search, /search/reviews
cd indexer && python3 -m pytest tests/ --tb=short   # pipeline stages, /index, /backfill
```

Each `conftest.py` puts the sibling `common/` and the local hevlayer SDK
checkout on `sys.path` so tests don't need pip installs.

## Agent Rules

- Prefer public DNS for laptop checks unless the task specifically needs an
  in-cluster bypass.
- Keep the three Python service boundaries intact:
  - Read-API HTTP contracts live in `search/app/`.
  - Indexer HTTP contracts and pipeline code live in `indexer/app/`.
  - Anything shared (Settings, records, embedders) goes in `common/hev_shop_common/`.
  Don't import indexer modules from search or vice versa.
- Run the narrowest meaningful tests for code changes, or explain why they
  were not run.
- Do not revert unrelated user changes.
