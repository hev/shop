# hev-shop

`hev-shop` is a live semantic shopping demo built on the Layer gateway. It takes
real product and review data from Amazon Reviews 2023, turns product images and
review text into vectors, writes them through Layer into Turbopuffer, and serves
a storefront where search, filtering, product pages, and review-derived tags are
backed by those vectors.

Links:

- [hev-shop](https://hev-shop.com) - the live running shop
- [hevlayer.com](https://hevlayer.com) - more detail on the Layer gateway
- [hevmesh.com](https://hevmesh.com) - more detail on the mesh substrate

## What This Is

The app is a complete workload for developers who want to see how Layer behaves
under an application-shaped indexing and search flow:

- Product image search uses [CLIP ViT-L/14](https://huggingface.co/openai/clip-vit-large-patch14).
- Review search uses [Qwen3 Embedding 8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B).
- Source data comes from [McAuley-Lab/Amazon-Reviews-2023](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023).
- Vectors land in Turbopuffer through Layer namespace APIs.
- Indexing work is coordinated through Layer pipeline APIs backed by PostgreSQL.
- KEDA scales workers from Layer PostgreSQL state instead of a separate queue.
- Karpenter NodePools can be deployed with the app, so pod scaling and node
  scaling live next to the workload that creates the demand.

The point is not to be a generic ecommerce starter. The point is to make Layer's
developer contract concrete: stage work, claim work, embed it, write vectors,
query with freshness signals, and let the gateway own the Turbopuffer edge.

## How It Works

```
Amazon Reviews 2023
        |
        v
  indexer API  ---- job rows ----> CPU product/review workers
        |                              |
        |                              v
        |                    Layer pipeline document staging
        |                              |
        v                              v
   Next.js web <---- search ---- indexer API ---- Layer gateway
                                             |         |
                                             |         +--> Layer PostgreSQL pipeline state
                                             |         +--> Aerospike chunk/cache data
                                             |         +--> Turbopuffer vector namespaces
                                             |
                                             +--> GPU workers claim/embed/complete
```

Product images land in the `amazon-products` namespace. Review text is sharded
across `amazon-reviews-*` namespaces, and classifier output is rolled back onto
product vectors as filterable tags.

## What To Inspect

- `indexer/app/layer_client.py` shows the app-facing Layer pipeline and namespace calls.
- `indexer/app/extraction.py` stages product images and review work.
- `indexer/app/embedding.py` claims product work and writes CLIP vectors.
- `indexer/app/review_workers.py` embeds reviews, classifies reviews, and rolls tags up.
- `web/app/api/search/route.ts` passes search through the backend and preserves `stable_as_of`.
- `helm/hev-shop` deploys the full app with PostgreSQL-driven KEDA autoscaling
  and optional Karpenter CPU/GPU NodePools.

## Repo Layout

```
cmd/                  Go CLI for health, indexing, status, scans, and direct gateway calls
client/               Small Go client for the Layer namespace API
indexer/              FastAPI service plus CPU/GPU/review worker code
kubernetes/           Raw Kubernetes manifests kept for low-level inspection
helm/hev-shop/        Standalone Helm chart for deploys
scripts/              Operational helper scripts
web/                  Next.js storefront and server-side API adapters
DESIGN.md             Pipeline and data model design
SEARCH_API.md         Search API contract used by the web app
REVIEWS_PIPELINE.md   Review indexing/classification fan-out plan
SCALING.md            Scale-test notes
```

## Local Development

Run the CLI:

```sh
go run . --help
go test ./...
```

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

Queue a small indexing job:

```sh
go run . index --count 1000 --category Electronics
go run . status --pipeline-id amazon-products-images
```

## Helm Deploy

The Helm chart assumes Layer is already installed and exposes:

- `layer-gateway.layer.svc.cluster.local:8080`
- `layer-postgres.layer.svc.cluster.local:5432`
- KEDA in the cluster
- Karpenter in the cluster when `karpenter.enabled=true`
- an RWX storage class for the shared image/model cache

Install:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace \
  --set indexerImage.repository=ghcr.io/hev/hev-shop-indexer \
  --set webImage.repository=ghcr.io/hev/hev-shop-web
```

Override the Layer PostgreSQL URL when Layer uses a managed database:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace \
  --set-string layer.databaseUrl='postgres://user:pass@host:5432/hevlayer'
```

The KEDA ScaledObjects use `connectionFromEnv: LAYER_DATABASE_URL`, so every
worker reads the same Layer PostgreSQL URL that the scaler uses for queue depth.

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

The default NodePools provide `mesh-role=app` CPU nodes and `mesh-role=gpu` GPU
nodes, matching the worker selectors in the chart.
