# hev-shop Agent Guide

This file is for engineering and operations work in `hev-shop`. For product,
design, and strategic context, read `CLAUDE.md`.

## Repo Layout

Two Python services + shared Python library + one Next.js app:

```text
hev-shop/
  search/                 # read API: /search, /recommend, /product, /meta
    app/{main,models}.py
    tests/
    Dockerfile, requirements.txt
  indexer/                # control plane + CPU/GPU workers
    app/                  # /index, /status + product extraction/embedding
      crds/               # app-owned Layer Pipeline/UDF YAML, if/when used
    tests/
    Dockerfile, requirements.txt
  common/                 # shared Settings, ProductRecord, CLIP embedders
    hev_shop_common/{config,records,embedders}.py
    tests/
    pyproject.toml
  web/                    # Next.js storefront
  helm/hev-shop/          # chart for search, indexer-api, web, workers
```

Search and indexer both pull `hev_shop_common` via `pip install -e ../common`.
The same pattern is used for the hev layer SDK in `../layer/clients/python`
from the repo root's sibling checkout layout.

## Live Endpoints

The app runs on EKS in namespace `hev-shop`, fronted by a shared ALB
(IngressGroup `hev-public`). Public DNS comes from
`../layer/infra/ingress/hev-shop/`.

| Surface | URL | Backed by Service |
|---|---|---|
| Storefront | https://hev-shop.com | `hev-shop-web` (port 80 to pod 3000) |
| Storefront (www) | https://www.hev-shop.com redirects to apex | LBC `redirect-to-apex` action |
| Read API | https://api.hev-shop.com/{search,recommend,product,meta,...} | `hev-shop-search` (port 8080) |
| Indexer API | https://api.hev-shop.com/{index,status} | `hev-shop-indexer-api` (port 8080) |
| Layer gateway | https://aws-us-east-1.hevlayer.com | `layer-gateway` in namespace `layer` (port 8080) |

`api.hev-shop.com` is path-routed by the ALB: `/search*`, `/recommend*`,
`/product*`, and `/meta*` go to `hev-shop-search`; `/index` and `/status`
go to `hev-shop-indexer-api`. Update the ingress under
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
curl -s -X POST -H 'content-type: application/json' \
  -d '{"asin":"B00FI7TCGI","top_k":3}' \
  https://api.hev-shop.com/recommend | jq .

# Indexer control plane
curl -s "https://api.hev-shop.com/status?pipeline_id=hev-shop-product-images" | jq .
```

The read-API request/response contract is in `search/app/main.py` (mirrored on
the storefront in `web/lib/backend.ts`); the indexer control-plane contract is
in `indexer/app/main.py`.

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
kubectl logs     -n hev-shop deploy/hev-shop-cpu-worker   --tail=200
kubectl logs     -n hev-shop deploy/hev-shop-gpu-worker   --tail=200
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
| `shop index --category Electronics --count 1000` | `POST /index` |
| `shop status --pipeline-id hev-shop-product-images` | `GET /status` |
| `shop health` | search `/healthz` + indexer `/status` |

The CLI talks to one host by default: `--api-base` (env `SHOP_API_BASE`,
default `https://api.hev-shop.com`). For port-forward dev, override either
service with `--search-url` / `--indexer-url`:

```sh
shop --search-url http://127.0.0.1:18080 meta
shop --indexer-url http://127.0.0.1:18081 status
```

## OpenAPI Specs

The committed specs at `search/openapi.json` and `indexer/openapi.json` are the
source of truth for the Go client. Regenerate after touching a route or
Pydantic model:

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
| `main.py` | FastAPI app: `/search`, `/recommend`, `/product/{asin}`, `/meta`, `/healthz` |
| `models.py` | Pydantic HTTP contracts for the read API |

Heavy lifting (Settings and CLIP embedder wrappers) is in `hev_shop_common`.
The search pod loads `CLIPTextEmbedder` to embed query strings.

## Indexer Service Layout

`indexer/app/`:

| File | Purpose |
|---|---|
| `main.py` | FastAPI control plane: `/index`, `/status`, `/healthz` |
| `worker.py` | Process entrypoint; `WORKER_TYPE=cpu` or `gpu` |
| `extraction.py` | CPU worker for extraction jobs and product chunk staging |
| `pipeline.py` | GPU product embedding worker using `put_pipeline_document_vectors` |
| `jobs.py` | Extraction job document shape |
| `dataset.py` | HuggingFace `McAuley-Lab/Amazon-Reviews-2023` product metadata reader |
| `models.py` | Pydantic HTTP contracts for `/index` and `/status` |
| `crds/` | Home for app-owned Layer Pipeline/UDF manifests if shop moves a pipeline to declarative ownership |

## Common Library

`common/hev_shop_common/`:

| File | Purpose |
|---|---|
| `config.py` | `pydantic_settings.BaseSettings` env-var config used by both services |
| `records.py` | `ProductRecord`, category normalizer, product vector attributes |
| `embedders.py` | `CLIPImageEmbedder` and `CLIPTextEmbedder` lazy-init wrappers |

## Pipeline Model

The product indexing path follows Layer's pipeline document lifecycle:

```text
CPU extraction: product metadata row -> put_pipeline_document_chunks -> pending
GPU embedding: claim pending -> fetch image bytes -> put_pipeline_document_vectors -> indexed
```

Extraction jobs are small control documents in `EXTRACTION_PIPELINE_ID`.
`WORKER_TYPE=cpu` claims those jobs and stages product chunks into `PIPELINE_ID`.
`WORKER_TYPE=gpu` claims pending product documents from `PIPELINE_ID` and writes
vectors. Product images are fetched in memory by the GPU worker and are not
cached on local disk.

App-owned Layer Pipeline/UDF YAML belongs under `indexer/app/crds/`. The Helm
chart should pass IDs/config and deploy Kubernetes workloads; it should not carry
pipeline shape definitions.

## Tests

Each service has its own pytest tree. Run the narrowest meaningful one for the
code you touched:

```sh
cd common  && python3 -m pytest tests/ --tb=short   # Settings + records
cd search  && python3 -m pytest tests/ --tb=short   # /search, /recommend, /product, /meta
cd indexer && python3 -m pytest tests/ --tb=short   # product pipeline, /index, /status
```

Go and frontend checks:

```sh
go test ./...
cd web && npm run build
helm lint ./helm/hev-shop
helm template hev-shop ./helm/hev-shop --namespace hev-shop >/tmp/hev-shop-rendered.yaml
```

Each Python `conftest.py` puts the sibling `common/` and local hev layer SDK
checkout on `sys.path` so tests do not need pip installs.

## Agent Rules

- Prefer public DNS for laptop checks unless the task specifically needs an
  in-cluster bypass.
- Keep the Python service boundaries intact:
  - Read-API HTTP contracts live in `search/app/`.
  - Indexer HTTP contracts and pipeline code live in `indexer/app/`.
  - Anything shared (Settings, records, embedders) goes in `common/hev_shop_common/`.
  Don't import indexer modules from search or vice versa.
- Run the narrowest meaningful tests for code changes, or explain why they
  were not run.
- Do not revert unrelated user changes.
