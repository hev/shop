# hev-shop Agent Guide

This file is for engineering and operations work in `hev-shop`. For product,
design, and strategic context, read `CLAUDE.md`.

## Repo Layout

Two Python services + shared Python library + one Next.js app + a Go
smoke-test CLI. The Python services are flat modules (no `app/` package),
matching the layout in https://hevlayer.com/docs/api/pipelines/:

```text
hev-shop/
  app/                    # Next.js storefront
  search/                 # read API: /search, /recommend, /product, /meta
    app.py, models.py
    tests/
    Dockerfile, requirements.txt, openapi.json
  indexer/                # control plane + pipeline worker scripts
    pipelines/            # Layer Pipeline resources (extract-chunk, embed)
    app.py                # /index, /status; creates the Layer queues
    extract_chunk.py      # CPU stage: claim job, read source, stage chunks
    embed.py              # GPU stage: claim pending docs, write CLIP vectors
    dataset.py            # HuggingFace product metadata reader
    tests/
    Dockerfile (api / extract-chunk / embed targets), requirements.txt
  common/                 # shared Settings, ProductRecord, CLIP embedders
    hev_shop_common/{config,records,embedders}.py
    tests/
    pyproject.toml
  tests/                  # Go `shop` CLI + generated clients (smoke tests)
  helm/hev-shop/          # chart for search, indexer-api, web pods only
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

The read-API request/response contract is in `search/models.py` (mirrored on
the storefront in `app/lib/backend.ts`); the indexer control-plane contract is
in `indexer/app.py`.

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

# Worker Deployments are created by the Layer operator from the Pipeline
# resources; list them by the operator's pipeline label instead of fixed names.
kubectl get pipelines.hevlayer.com -n hev-shop
kubectl get deploy -n hev-shop -l layer.hev.dev/component=worker 2>/dev/null \
  || kubectl get deploy -n hev-shop
```

## `shop` CLI

The smoke-test CLI lives in `tests/` and drives the nightly + e2e workflows.
Every hev-shop endpoint has a matching subcommand. Build or run it from there
(`cd tests && go run . <cmd>`, or `go build -o /tmp/shop .`).

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
make codegen    # regenerates tests/client/searchapi + tests/client/indexerapi
```

`tests/test_openapi_spec.py` in each service fails CI-like checks if the
committed spec drifts from the FastAPI app.

## Search Service Layout

`search/`:

| File | Purpose |
|---|---|
| `app.py` | FastAPI app: `/search`, `/recommend`, `/product/{asin}`, `/meta`, `/healthz` |
| `models.py` | Pydantic HTTP contracts for the read API |

Heavy lifting (Settings and CLIP embedder wrappers) is in `hev_shop_common`.
The search pod loads `CLIPTextEmbedder` to embed query strings.

## Indexer Service Layout

`indexer/`:

| File | Purpose |
|---|---|
| `app.py` | FastAPI control plane: `/index`, `/status`, `/healthz` + the HTTP contracts. The only place that creates the Layer queues (`ensure_pipeline`) |
| `extract_chunk.py` | CPU stage script: claims extraction jobs, reads the source, stages product chunks. Carries the job document shape |
| `embed.py` | GPU stage script: claims pending product docs, writes vectors with `put_pipeline_document_vectors` |
| `dataset.py` | HuggingFace `McAuley-Lab/Amazon-Reviews-2023` product metadata reader |
| `pipelines/` | Layer `Pipeline` resources declaring the two worker stages (image, pool, scaling). `kubectl apply -f indexer/pipelines/` |

Worker pods are owned by the Layer operator, which injects
`HEVLAYER_PIPELINE_ID`, `HEVLAYER_BASE_URL`, and `LAYER_GATEWAY_API_KEY`;
everything else rides on `Settings` code defaults. There is no `WORKER_TYPE`
dispatch — each stage script is its own container command (see the
`extract-chunk` and `embed` targets in `indexer/Dockerfile`).

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

Extraction jobs are small control documents in the `hev-shop-extraction-jobs`
queue, staged by `POST /index`. The `extract-chunk` Pipeline's workers claim
those jobs and stage product chunks into `hev-shop-product-images`; the
`embed` Pipeline's workers claim pending product documents from it and write
vectors. Product images are fetched in memory by the GPU worker and are not
cached on local disk.

Worker deployment shape (image, compute pool, scaling) is declared in the
Pipeline resources under `indexer/pipelines/` and reconciled by the Layer
operator — including the KEDA ScaledObjects. The queues themselves are still
created via the SDK (`ensure_pipeline` in `indexer/app.py`), since the
operator manages Kubernetes objects, not gateway state. The Helm chart only
deploys the always-on API/web pods; it carries no worker or pipeline shape.
The `cpu-large` and `gpu` compute pools referenced by `scaling.pool` are
defined in the Layer chart's `InfraRules/default`
(`../layer/infra/helm/layer/values.yaml`).

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
cd tests && go test ./... -count=1
cd app && npm run build
helm lint ./helm/hev-shop
helm template hev-shop ./helm/hev-shop --namespace hev-shop >/tmp/hev-shop-rendered.yaml
kubectl apply --dry-run=client -f indexer/pipelines/
```

Each Python `conftest.py` puts the sibling `common/` and local hev layer SDK
checkout on `sys.path` so tests do not need pip installs.

## Agent Rules

- Prefer public DNS for laptop checks unless the task specifically needs an
  in-cluster bypass.
- Keep the Python service boundaries intact:
  - Read-API HTTP contracts live in `search/`.
  - Indexer HTTP contracts and pipeline code live in `indexer/`.
  - Anything shared (Settings, records, embedders) goes in `common/hev_shop_common/`.
  Don't import indexer modules from search or vice versa.
- Run the narrowest meaningful tests for code changes, or explain why they
  were not run.
- Do not revert unrelated user changes.
