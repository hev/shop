# hev-shop

`hev-shop` is a developer example app for the Layer gateway in
`apps/layer-gateway`. It indexes Amazon product images and reviews, writes
vectors through the gateway into Turbopuffer, and exposes a storefront that
shows what the gateway APIs make possible.

This repository is private while under construction. No public license is
granted yet. The intended public license is MIT before the repo is opened.

## What It Shows

- Turbopuffer namespace writes, fetches, scans, and vector queries through
  `apps/layer-gateway`.
- Gateway-managed consistency watermarks with `stable_as_of` on search
  responses.
- Pipeline staging, claiming, heartbeats, and stage transitions backed by
  PostgreSQL.
- CPU and GPU worker split: CPU workers prepare product/review work; GPU
  workers embed images and review text; CPU review workers classify and roll up
  tags.
- KEDA/Karpenter scaling driven by gateway pipeline state instead of custom
  queue glue.

The app is intentionally not a generic ecommerce template. Its job is to be a
concrete, inspectable workload for the gateway's Turbopuffer and pipeline
surface.

## Architecture

```
Amazon Reviews 2023
        |
        v
  indexer API  ---- queue rows ----> CPU workers
        |                              |
        |                              v
        |                    /v2/pipelines/.../documents
        |                              |
        v                              v
   Next.js web <---- search ---- indexer API ---- layer-gateway
                                             |         |
                                             |         +--> PostgreSQL pipeline state
                                             |         +--> Aerospike chunk/cache data
                                             |         +--> Turbopuffer vectors
                                             |
                                             +--> GPU workers claim/embed/complete
```

Product images land in the `amazon-products` Turbopuffer namespace. Review text
is sharded across `amazon-reviews-*` namespaces, and review classifier tags are
rolled back onto the product vectors as filterable attributes.

## Repo Layout

```
cmd/                  Go CLI for health, indexing, status, scans, and direct gateway calls
client/               Small Go client for the layer-gateway namespace API
indexer/              FastAPI service plus CPU/GPU/review worker code
kubernetes/           App deployments, services, KEDA ScaledObjects, PVC, config
scripts/              Private construction deploy and scale-run helpers
web/                  Next.js storefront and server-side API adapters
DESIGN.md             Pipeline and data model design
SEARCH_API.md         Search API contract used by the web app
REVIEWS_PIPELINE.md   Review indexing/classification fan-out plan
SCALING.md            Current scale-test notes
```

## Prerequisites

- A running `apps/layer-gateway` with `TURBOPUFFER_API_KEY`, Aerospike, and
  PostgreSQL configured.
- Turbopuffer access for the target namespaces.
- Python 3.12 for the indexer and workers.
- Node 22 for the web app.
- Go 1.25 for the CLI.
- Optional: Hugging Face token for private/rate-limited dataset access.
- Optional: OpenRouter key for review classification.

During private construction, `scripts/deploy.sh` can read Terraform outputs
from the sibling mesh repo:

```sh
MESH_REPO=../mesh scripts/deploy.sh --build-web
```

The private EKS helper that installs Karpenter and the `hev-shop` CPU/GPU
NodePools follows the same convention:

```sh
MESH_REPO=../mesh scripts/deploy-karpenter.sh
```

For a standalone deployment, provide the values directly:

```sh
ECR_REPOSITORY_URL=... \
ECR_WEB_URL=... \
CLUSTER_NAME=... \
HEV_SHOP_EFS_FILE_SYSTEM_ID=... \
scripts/deploy.sh --build-web
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
DATA_DIR=../data uvicorn app.main:app --host 0.0.0.0 --port 8090
```

Run the storefront in mock mode:

```sh
cd web
npm install
npm run dev
```

Point the storefront at the API:

```sh
cd web
HEV_SHOP_API_BASE=http://127.0.0.1:8090 npm run dev
```

Queue a small indexing job against a running API:

```sh
go run . index --count 1000 --category Electronics
go run . status --pipeline-id amazon-products-images
```

## Gateway Flow

1. `POST /index` creates product extraction jobs in the app database.
2. CPU workers stream Amazon metadata, download images, and stage product chunks
   through `PUT /v2/pipelines/{pipeline}/documents/{asin}`.
3. GPU workers claim staged documents with `POST /v2/pipelines/{pipeline}/claim`,
   embed images, upsert vectors through the gateway, heartbeat long claims, and
   mark documents `indexed`.
4. Search requests encode query text and call
   `POST /v2/namespaces/{namespace}/query` through the gateway. Responses carry
   `stable_as_of` when the gateway has a safe Turbopuffer watermark.
5. Review workers use the same pipeline primitives for fan-out: embed review
   chunks, classify review text, and roll product tags back into the product
   namespace.

The gateway contract is documented in the mesh repo:

- `apps/layer-gateway/docs/guides/namespaces.md`
- `apps/layer-gateway/docs/guides/pipelines.md`

## Kubernetes

The manifests assume:

- `layer-gateway` is reachable at
  `http://layer-gateway.layer.svc.cluster.local:8080`.
- KEDA is installed.
- An RWX storage class named `hev-shop-efs` exists for the shared `/data` PVC.
- CPU workers can schedule on `mesh-role=app` nodes.
- GPU workers can schedule on `mesh-role=gpu` nodes with the NVIDIA device
  plugin installed.

See [kubernetes/README.md](./kubernetes/README.md) for deploy and scale-run
commands.
