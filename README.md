# hev-shop

`hev-shop` is a live semantic shopping demo built on the Layer gateway. It
reads product metadata from Amazon Reviews 2023, embeds product images with
CLIP, writes vectors through Layer into Turbopuffer, and serves a storefront
with product search, recommendations, product detail pages, and Layer freshness
signals.

Links:

- [hev-shop](https://hev-shop.com) - the live running shop
- [hevlayer.com](https://hevlayer.com) - more detail on the Layer gateway
- [hevmesh.com](https://hevmesh.com) - more detail on the mesh substrate

## What This Is

The app is a complete workload for developers who want to see how Layer behaves
under an application-shaped indexing and search flow:

- Source data comes from [McAuley-Lab/Amazon-Reviews-2023](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023).
- Product vectors land in Turbopuffer through Layer pipeline vector writes.
- Indexing work is coordinated through Layer pipeline APIs.
- KEDA scales workers from Layer pipeline metrics instead of a separate queue.
- Karpenter NodePools can be deployed with the app, so pod scaling and node
  scaling live next to the workload that creates demand.

The point is not to be a generic ecommerce starter. The point is to make
Layer's developer contract concrete: stage product chunks, claim pending work,
embed it, write vectors through the pipeline API, query with freshness signals,
and let the gateway own the Turbopuffer edge.

## Feature Highlights

- **Semantic image-based product search with CLIP.** The app embeds product
  images with [CLIP ViT-L/14](https://huggingface.co/openai/clip-vit-large-patch14)
  and stores one product vector per ASIN.
- **Product recommendations.** `/recommend` uses Layer's `nearest_to_id` query
  mode to find visually similar products from an indexed ASIN.
- **Facet snapshots through Layer.** Category exploration is driven through
  Layer's namespace snapshot API, so the app can inspect indexed product state
  without building a warehouse path for every facet.
- **Declarative two-stage pipeline.** The CPU extract and GPU embed stages are
  Layer `Pipeline` resources (`indexer/pipelines/`); the Layer operator owns
  their Deployments and KEDA scaling. Workers are plain scripts: claim pending
  work, embed it, call `put_pipeline_document_vectors`. Optional Karpenter
  NodePools add CPU/GPU capacity.

## How It Works

```text
Amazon Reviews 2023 product metadata
        |
        v
  indexer API  ---- extraction docs ----> CPU extraction workers
        |                                     |
        |                                     v
        |                         Layer product pipeline chunks
        |                                     |
        v                                     v
   Next.js web <---- search API <---- Layer gateway <---- GPU CLIP workers
                                             |
                                             +--> Layer pipeline state + metrics
                                             +--> Aerospike chunk/cache data
                                             +--> Turbopuffer product namespace
```

CPU workers stage product chunks containing product metadata and source image
URLs. GPU workers fetch images directly into memory, embed them with CLIP, and
write vectors through the product pipeline. No product images are cached on
local disk.

## What To Inspect

- `hevlayer` (Python SDK) — the indexer talks to layer-gateway through the
  official `hevlayer.AsyncHevlayer` client (see `clients/python` in the layer
  repo). The SDK covers namespace query/fetch APIs, pipeline chunk/vector
  writes, claim/heartbeat APIs, and Layer snapshot/cache APIs.
- `indexer/pipelines/` — the two Layer `Pipeline` resources (extract-chunk +
  embed) that declare worker images, pools, and scaling.
- `indexer/extract_chunk.py` — CPU worker that drains extraction jobs and
  stages product chunks into the product pipeline.
- `indexer/embed.py` — GPU product embedding loop that claims pending docs,
  fetches image bytes in memory, and writes vectors with
  `put_pipeline_document_vectors`.
- `indexer/app.py` — FastAPI control plane: `/index`, `/status`, and
  `/healthz`. The one place that creates the Layer queues.
- `search/app.py` — read API: `/search`, `/recommend`, `/product/{asin}`,
  `/meta`, and `/healthz`.
- `app/app/api/search/route.ts` and `app/lib/backend.ts` — storefront backend
  adapters that preserve Layer `stable_as_of` and perf metadata.
- `helm/hev-shop` — deploys search, indexer API, and web, plus optional
  Karpenter NodePools. Workers are operator-owned, not chart-owned.

## Repo Layout

```text
app/                  Next.js storefront and server-side API adapters
search/               Read API: app.py, models.py (/search, /recommend, ...)
indexer/              Pipeline service: app.py, extract_chunk.py, embed.py,
                      dataset.py, and pipelines/*.yaml Pipeline resources
common/               Shared Settings, product records, and CLIP embedders
helm/hev-shop/        Standalone Helm chart for the three API/web deploys
tests/                Go smoke-test CLI (`shop`) + generated API clients
scripts/              Operational helper scripts
```

## Local Development

Run the indexer API:

```sh
cd indexer
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=/tmp/hev-shop-data uvicorn app:app --host 0.0.0.0 --port 8090
```

Run the storefront in mock mode:

```sh
cd app
npm install
npm run dev
```

Point the storefront at a running API:

```sh
cd app
HEV_SHOP_API_BASE=http://127.0.0.1:8090 npm run dev
```

The `shop` smoke-test CLI lives in `tests/` (it drives the nightly and e2e
workflows; every endpoint has a matching subcommand):

```sh
cd tests
go run . meta
go run . search "wireless headphones" --top-k 3
go run . recommend B00FI7TCGI --top-k 3
go run . product B00FI7TCGI
go test ./...
```

By default it talks to `https://api.hev-shop.com`. Override with `--api-base`
(or env `SHOP_API_BASE`), or point at individual services with `--search-url`
/ `--indexer-url` for port-forward dev.

Queue a small indexing job:

```sh
cd tests
go run . index --count 1000 --category Electronics
go run . status --pipeline-id hev-shop-product-images
```

OpenAPI specs are committed at `search/openapi.json` and
`indexer/openapi.json`; regenerate after editing a route or model:

```sh
make openapi   # dump from the FastAPI apps
make codegen   # regenerate the Go clients in tests/client/*api/
```

## Helm Deploy

The Helm chart assumes Layer is already installed and exposes:

- `layer-gateway.layer.svc.cluster.local:8080`
- `layer-gateway.layer.svc.cluster.local:8080/v2/metrics` for Prometheus-compatible metric queries
- KEDA in the cluster
- Karpenter in the cluster when `karpenter.enabled=true`
- an RWX storage class for the shared dataset cache

Install:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace \
  --set indexerImage.repository=ghcr.io/hev/hev-shop-indexer \
  --set searchImage.repository=ghcr.io/hev/hev-shop-search \
  --set webImage.repository=ghcr.io/hev/hev-shop-web
kubectl apply -f indexer/pipelines/
```

The chart deploys the three always-on pods (search, indexer API, web). The
workers are the two `Pipeline` resources in `indexer/pipelines/` — the Layer
operator creates their Deployments and KEDA ScaledObjects from pipeline queue
depth, so hev-shop never needs Layer PostgreSQL credentials. Their `gpu` /
`cpu-large` compute pools come from the Layer chart's `InfraRules/default`.

For EKS deploys, `scripts/deploy.sh` is a wrapper that builds and pushes the
images (the indexer Dockerfile has `api`, `extract-chunk`, and `embed`
targets), runs `helm upgrade --install`, and applies `indexer/pipelines/`
with the pushed image tags.

Enable app-owned Karpenter NodePools:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace \
  --set karpenter.enabled=true \
  --set karpenter.clusterName=<eks-cluster-name> \
  --set karpenter.kubernetesVersion=<eks-version> \
  --set karpenter.nodeInstanceProfile=<karpenter-node-instance-profile>
```

The default NodePools provide `layer.hev.dev/node-role=worker-cpu` CPU nodes
and `layer.hev.dev/node-role=worker-gpu` GPU nodes, matching the worker
selectors in the chart.
