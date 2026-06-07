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
- **Two-worker Kubernetes pipeline.** CPU extraction workers stage product
  chunks; GPU workers claim pending product docs, fetch image bytes in memory,
  and call `put_pipeline_document_vectors`. KEDA reads Layer pipeline metrics
  to scale pods, while optional Karpenter NodePools add CPU/GPU capacity.

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
- `indexer/app/extraction.py` — CPU worker that drains extraction jobs and
  stages product chunks into the product pipeline.
- `indexer/app/pipeline.py` — GPU product embedding loop that claims pending
  docs, fetches image bytes in memory, and writes vectors with
  `put_pipeline_document_vectors`.
- `indexer/app/main.py` — FastAPI control plane: `/index`, `/status`, and
  `/healthz`.
- `search/app/main.py` — read API: `/search`, `/recommend`, `/product/{asin}`,
  `/meta`, and `/healthz`.
- `web/app/api/search/route.ts` and `web/lib/backend.ts` — storefront backend
  adapters that preserve Layer `stable_as_of` and perf metadata.
- `helm/hev-shop` — deploys search, indexer API, web, CPU extraction workers,
  GPU embedding workers, KEDA ScaledObjects, and optional Karpenter NodePools.

## Repo Layout

```text
cmd/                  Cobra subcommands for the `shop` CLI
client/searchapi/     oapi-codegen-generated Go client for search/openapi.json
client/indexerapi/    oapi-codegen-generated Go client for indexer/openapi.json
common/               Shared Settings, product records, and CLIP embedders
indexer/              FastAPI control plane plus CPU/GPU worker code
helm/hev-shop/        Standalone Helm chart for deploys
scripts/              Operational helper scripts
web/                  Next.js storefront and server-side API adapters
```

## Local Development

Install the CLI:

```sh
go install github.com/hev/shop@latest
shop --help
```

Or run from a checkout:

```sh
go run . --help
go test ./...
```

By default the CLI talks to `https://api.hev-shop.com`. Override with
`--api-base` (or env `SHOP_API_BASE`), or point at individual services with
`--search-url` / `--indexer-url` for port-forward dev.

Run the indexer API:

```sh
cd indexer
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=/tmp/hev-shop-data uvicorn app.main:app --host 0.0.0.0 --port 8090
```

Run the storefront in mock mode:

```sh
cd web
npm install
npm run dev
```

Point the storefront at a running API:

```sh
cd web
HEV_SHOP_API_BASE=http://127.0.0.1:8090 npm run dev
```

Try the CLI against the deployed API:

```sh
shop meta
shop search "wireless headphones" --top-k 3
shop recommend B00FI7TCGI --top-k 3
shop product B00FI7TCGI
```

Queue a small indexing job:

```sh
shop index --count 1000 --category Electronics
shop status --pipeline-id hev-shop-product-images
```

OpenAPI specs are committed at `search/openapi.json` and
`indexer/openapi.json`; regenerate after editing a route or model:

```sh
make openapi   # dump from the FastAPI apps
make codegen   # regenerate the Go clients in client/*api/
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
```

For EKS deploys, `scripts/deploy.sh` is a Helm wrapper. It can optionally build
and push indexer, search, and web images, then runs `helm upgrade --install`.

The KEDA ScaledObjects use Prometheus queries against
`layer_pipeline_stage_count`, so hev-shop never needs Layer PostgreSQL
credentials.

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

The default NodePools provide `mesh-role=app` CPU nodes and `mesh-role=gpu`
GPU nodes, matching the worker selectors in the chart.
