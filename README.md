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

- Source data comes from [McAuley-Lab/Amazon-Reviews-2023](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023).
- Vectors land in Turbopuffer through Layer namespace APIs.
- Indexing work is coordinated through Layer pipeline APIs backed by PostgreSQL.
- KEDA scales workers from Layer PostgreSQL state instead of a separate queue.
- Karpenter NodePools can be deployed with the app, so pod scaling and node
  scaling live next to the workload that creates the demand.

The point is not to be a generic ecommerce starter. The point is to make Layer's
developer contract concrete: stage work, claim work, embed it, write vectors,
query with freshness signals, and let the gateway own the Turbopuffer edge.

## Feature Highlights

- **Semantic image-based product search with CLIP.** The app embeds product
  images with [CLIP ViT-L/14](https://huggingface.co/openai/clip-vit-large-patch14)
  and stores one product vector per ASIN. This is an app-level retrieval feature
  that gives the Layer/Turbopuffer path a real visual-search workload.
- **Facet scans through Layer.** Category and attribute exploration can be
  driven through Layer's namespace scan API, so the app can inspect indexed
  product state without building a separate warehouse path for every facet.
- **Multi-stage autoscaling Kubernetes pipeline.** CPU extraction, GPU image
  embedding, GPU review embedding, LLM classification, and tag aggregation run
  as separate workers. KEDA reads Layer PostgreSQL pipeline state to scale pods,
  while optional Karpenter NodePools add the CPU/GPU node capacity those pods
  require.
- **Review-based LLM classifier to improve product search.** Review text is
  embedded with [Qwen3 Embedding 8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B)
  and classified with an LLM. The app rolls supported review tags back onto
  product vectors, improving product search and filtering with customer-language
  signals. Like CLIP image search, this is app logic that helps frame why the
  Layer gateway surface matters.

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

- `indexer/app/layer_client.py` — the single HTTP path to the Layer gateway.
  Every Layer call in the app goes through this file, including the
  turbopuffer-compatible namespace surface (query/upsert/patch/fetch), the
  pipeline state machine (create/claim/heartbeat/stage), and the
  Layer-specific scan and document-cache APIs.
- `indexer/app/pipeline.py` — the N-stage pipeline. One `STAGES` manifest plus
  a `run_stage` driver that owns the claim/heartbeat/release lifecycle, so
  each stage's `process_*` is just the work that's unique to that stage.
  Stages: `embed-products` (CLIP), `embed-reviews` (Qwen), `classify-reviews`
  (OpenRouter), `aggregate-tags` (postgres rollup → PATCH product rows).
- `indexer/app/extraction.py` — the CPU extraction worker that drains the
  Postgres job queue and stages products + raw reviews into the layer
  pipelines.
- `indexer/app/main.py` — FastAPI surface: `/search`, `/search/reviews`,
  `/product/{asin}`, `/meta`, `/index`, `/backfill`.
- `web/app/api/search/route.ts` and `web/lib/backend.ts` — passes search
  through the backend and preserves `stable_as_of`.
- `helm/hev-shop` deploys the full app with PostgreSQL-driven KEDA autoscaling
  and optional Karpenter CPU/GPU NodePools.

For the "what does Layer add over turbopuffer" framing, see
[`docs/LAYER_GATEWAY_SHOWCASE.md`](docs/LAYER_GATEWAY_SHOWCASE.md).

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
