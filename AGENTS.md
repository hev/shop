# hev-shop

A public storefront demo on hev layer over Amazon Reviews 2023 product data:
semantic product search, visually similar recommendations and product detail,
backed by CLIP image vectors that a two-stage Layer pipeline writes into
`amazon-products`. shop has no RFC of its own; its trending surface follows
`../layer-pro/docs/rfcs/0040-trending-searches-reduce-udfs.md`. `README.md` is
the public tour.

**This repo is public.** Never put client names, client systems or anything
from a client engagement in code, comments, docs or commit messages.

## You are a Layer customer

shop exists to use Layer the way a customer would and to report what it hits.
The demo working is table stakes; the report is the deliverable.

- **Reimplement nothing Layer owns:** queues and the document lifecycle
  (chunk, claim, heartbeat, vector write), worker scaling, facet snapshots,
  freshness watermarks, blob storage and cache warming. If you're writing
  vector bookkeeping or a queue, the boundary is wrong.
- **Read the docs, don't invent API.** Request and response shapes are in
  `../layer-pro/site/src/content/docs/` (public: https://hevlayer.com/docs)
  and `../layer-pro/apps/layer-gateway/openapi.yaml`.
- **Report friction in Linear** with the `linear` CLI: a bug or a wrong or
  missing doc is an issue on team `LYR`; a capability gap is an RFC, written
  as a Linear project with an `RFC: <name>` document (not a numbered file in
  `../layer-pro/docs/rfcs/`), with this workload as the motivating case. Drift between what the SDK and
  the `Pipeline` YAML can express is a Layer bug, not something to work
  around here.
- **Layer operates itself.** Autoscaling, scale-to-zero and scheduling are
  Layer's job; don't hand-tune them. If you must intervene to keep the demo
  up (shop shares `layer-prod` with the other demos), the intervention gets
  a `LYR` issue too.

## Layout and boundaries

- `app/` — Next.js storefront. Server-side adapters in `app/lib/backend.ts`
  (mirrors `search/models.py`) and `app/lib/hevlayer-client.ts`, which uses
  the TS client vendored in `app/vendor/hevlayer`
  (refresh with `scripts/sync-ts-client.sh` from `../layer-pro/clients/typescript`).
- `search/` — read API: `/search`, `/search/trending`, `/recommend`,
  `/product/{asin}`, `/meta`, `/drops`, `/healthz`. Embeds queries with CLIP text on CPU.
- `indexer/` — control plane (`app.py`: `/index`, `/index/checkpoint`,
  `/status`; the only place
  that creates the Layer queues via `ensure_pipeline`), the CPU stage
  (`extract_chunk.py`), the GPU stage (`embed.py`), and the Layer resources:
  `pipelines/` (`Pipeline`, Warehouse), `udfs/` (`Function`s
  `hev-shop-trending` and `hev-shop-warm-blobs`), `indexes/`.
- `common/hev_shop_common/` — `Settings` (every env var name and default is in
  `config.py`), `ProductRecord`, CLIP embedders. Search and indexer never
  import each other; shared code goes here.
- `tests/` — the Go `shop` smoke-test CLI (one subcommand per endpoint) and
  generated clients. It drives `nightly.yml`.

Worker shape is declarative, the document lifecycle is SDK calls: the Layer
operator reconciles `indexer/pipelines/` into worker Deployments and KEDA
ScaledObjects and injects `HEVLAYER_PIPELINE_ID`, `HEVLAYER_BASE_URL` and
`LAYER_GATEWAY_API_KEY`. The Helm chart owns only search, indexer-api and web.

## Run and test

The `hevlayer` Python SDK is on PyPI (0.6.0). The conftests prefer the
sibling source checkout at `../layer-pro/clients/python/src` when it exists
(factory worktrees aren't siblings of it; use `~/workspace/shop`), else the
installed package.

```sh
pip install pytest fastapi 'httpx>=0.27' 'pydantic-settings>=2.6' numpy pillow datasets hevlayer
(cd common && python -m pytest tests/ -q)
(cd search && python -m pytest tests/ -q)
(cd indexer && python -m pytest tests/ -q)
(cd tests && go test ./... -count=1)
(cd app && npm run build)
helm lint ./helm/hev-shop
make openapi && make codegen   # after touching a route or Pydantic model; CI checks drift
```

Secrets come from 1Password at run time, never a `.env` file. The gateway key
is `op://mesh-staging/layer-turbopuffer/credential`:

```sh
LAYER_GATEWAY_API_KEY=op://mesh-staging/layer-turbopuffer/credential \
  op run -- uvicorn app:app --port 8090          # from indexer/ or search/
```

Live checks go through public DNS (`shop meta`, `shop health`, or
`curl https://api.hev-shop.com/meta`); port-forward `svc/hev-shop-search`
only when you need to bypass the ALB.

## Deploy

shop is the exception in the demo family: API and web run on the cluster via
Helm (no Cloudflare Worker), with GPU CLIP embedding.

- **Cluster:** namespace `hev-shop` on EKS `layer-prod`, Helm release
  `hev-shop` from `./helm/hev-shop`. `scripts/deploy.sh` builds with depot,
  pushes, upgrades the release and applies `indexer/pipelines/` with the new
  tags; it does not apply `indexer/udfs/`, so `kubectl apply -f indexer/udfs/`
  after it. The chart reads the gateway key from the `layer` secret in the
  namespace (`secrets.gatewayKeySecret`); an empty key shows up as non-200s
  from the read API.
- **Images** go to the mesh-account ECR, never `ghcr.io`:
  `186219257916.dkr.ecr.us-east-1.amazonaws.com/hev-shop-{search,indexer,web}`
  (the indexer image has `api`, `extract-chunk` and `embed` targets). Never
  point a `Pipeline`/`Function` `image:` at a `ghcr.io/hev/*` placeholder.
  Image builds take `--build-context layer_client=../layer-pro/clients/python`.
- **Pools:** `extract-chunk` runs on `cpu-large`, `embed` on `gpu`; both pools
  come from `InfraRules/default` in the Layer chart
  (`../layer-pro/infra/helm/layer/values.yaml`). Optional app-owned Karpenter
  NodePools: `karpenter.enabled=true`.
- **Ingress:** `hev-shop.com` and `api.hev-shop.com` (path-routed to search
  and indexer-api) join the shared ALB IngressGroup `hev-public`. The manifests
  still live in `../layer-pro/infra/ingress/hev-shop/`, not in this chart; add
  new API routes there.

## State (2026-09-27)

The storefront and API are up on `layer-prod` (search, indexer-api and web
pods running; chart revision from 2026-06-24). `amazon-products` holds ~291k
product vectors across eight categories with a stable watermark. The
extract-chunk Pipeline runs on a nightly cron (02:00 UTC) and embed scales
from queue depth; both Functions and both worker Deployments are at zero
between runs. CI's Go job fails on codegen drift (`oapi-codegen@latest`
formats the generated clients differently from the committed ones); run
`make codegen` with a current oapi-codegen and commit to clear it.
