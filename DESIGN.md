# hev-shop: Indexing Pipeline Design

> **Status: implemented.** This is the original design doc, kept for the
> rationale, data model, and infra framing. Tasks L1–L12 and S1–S9 in the
> work breakdown are all shipped. The current code lives in
> `indexer/app/pipeline.py` (stages + driver) and `indexer/app/extraction.py`
> (raw ingest); the Layer client is now the official `hevlayer` Python SDK
> (`clients/python` in the layer repo). See `AGENTS.md` for the up-to-date
> module map.

## Overview

Two-stage product image indexing pipeline using CLIP, extended with a review
fan-out pipeline. CPU workers prep products/reviews; GPU workers embed product
images and review text chunks; CPU review workers classify reviews and roll tag
signals back onto product vectors. KEDA auto-scales workers off PostgreSQL queue
state.

## Document Model

**Turbopuffer namespace:** `amazon-products`
**Embedding model:** CLIP ViT-L/14 (768d), configurable via `CLIP_MODEL_NAME`
**Distance metric:** cosine_distance

```
id:            string    # ASIN
vector:        [768]f32  # CLIP image embedding

# filterable attributes
category:       string
avg_rating_txt: string
rating_cnt_txt: string

# returnable attributes
title:         string
description:   string
image_url:     string
image_path:    string    # PVC path: /data/images/{asin}.jpg
```

Raw numeric fields such as `avg_rating` and `rating_count` stay in the staged
pipeline chunk metadata. The final Turbopuffer vector attributes use stable
string fields to avoid conflicts with Turbopuffer's inferred namespace schema.

One product = one image = one vector. Reviews are staged as separate work items
in `hev-shop-reviews`: the search path chunks each review into 256-token windows
with 32-token overlap and writes Qwen text vectors to `amazon-reviews-*` shards;
the classifier path writes Phase 1 tags back to product attrs.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  hev-shop indexer (Python/FastAPI)                   │
│                                                      │
│  Runtime: stream/cache HF dataset → PVC /data/dataset/│
│                                                      │
│  POST /index  { count: 100000, category: "Electronics" }│
│  GET  /status                                        │
│                                                      │
│  CPU mode (WORKER_TYPE=cpu):                         │
│    claim extraction jobs from Layer pipeline API     │
│    for each product:                                 │
│      stream metadata from HuggingFace                │
│      download image → PVC /data/images/{asin}.jpg    │
│      PUT /v2/pipelines/{id}/documents/{asin}         │
│        chunks: [{ id: asin, image_path, attributes }]│
│                                                      │
│  GPU mode (WORKER_TYPE=gpu):                         │
│    loop:                                             │
│      POST /v2/pipelines/{id}/claim                   │
│      load images from PVC                            │
│      CLIP encode micro-batches                       │
│      POST /v2/namespaces/{namespace}                 │
│        upserts: 10k vectors per request              │
│      POST /v2/pipelines/{id}/documents/stage         │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  layer-gateway                           │
│                                          │
│  Pipeline API:                           │
│    POST   /v2/pipelines                  │
│    GET    /v2/pipelines/{id}/status       │
│    PUT    /v2/pipelines/{id}/documents/{d}│
│    GET    .../documents/{d}/chunks        │
│    PUT    .../documents/{d}/vectors       │
│                                          │
│  Storage:                                │
│    Embedded Aerospike — chunk data       │
│    Embedded PostgreSQL — pipeline state  │
│    Gateway metrics — KEDA signal         │
│    Turbopuffer — final vectors           │
└──────────────────────────────────────────┘
       │              │
  Shared PVC      KEDA polls gateway metrics
  /data/          scales GPU workers 0→N
  ├── dataset/
  └── images/
```

## Dataset

**Source:** `McAuley-Lab/Amazon-Reviews-2023` on HuggingFace
**Default category:** `Electronics` (1.6M products)
**Config:** `raw_meta_Electronics` split, streamed as parquet

The indexer downloads the category metadata on startup. Product image URLs are in the `images` field (list of dicts with `large`, `thumb`, `hi_res` keys). We grab the first available hi-res or large URL.

### Init options

```
POST /index
{
  "count": 100000,                       # -1 for all
  "category": "Electronics",             # HF config name
  "categories": ["Electronics", "Books"], # optional fan-out, overrides category
  "pipeline_id": "hev-shop-product-images",
  "job_size": 10000
}
```

## Pipeline State Machine

Managed by layer-gateway in PostgreSQL.

```
pending ──► embedding ──► indexed
   ▲             │
   └─────────────┘ stale lease recovery

failed
```

### `pipeline_documents` table

```sql
CREATE TABLE pipeline_documents (
    pipeline_id     TEXT NOT NULL,
    document_id     TEXT NOT NULL,
    stage           TEXT NOT NULL DEFAULT 'pending',
    chunk_count     INT NOT NULL DEFAULT 0,
    chunk_ids       JSONB NOT NULL DEFAULT '[]',
    claimed_by      TEXT,
    claimed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (pipeline_id, document_id)
);

CREATE INDEX idx_pipeline_stage ON pipeline_documents (pipeline_id, stage);
```

### `pipelines` table

```sql
CREATE TABLE pipelines (
    id               TEXT PRIMARY KEY,
    target_namespace TEXT NOT NULL,
    distance_metric  TEXT NOT NULL DEFAULT 'cosine_distance',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Implemented Claiming

- CPU workers claim extraction-job documents from the Layer extraction pipeline, download images, and stage one chunk per ASIN.
- Embedding, classification, and aggregation workers claim pipeline documents through layer-gateway, heartbeat active claims, and ask layer-gateway to move rows to `pending`, `failed`, or `indexed`.

```
POST /v2/pipelines/{id}/claim
{ "stage": "pending", "claim_stage": "embedding", "limit": 2000, "worker_id": "gpu-worker-0", "lease_seconds": 900 }
→
{ "documents": ["B07XYZ123", "B08ABC456", ...] }
```

Layer-gateway implements claims with `FOR UPDATE SKIP LOCKED`, records
`claimed_by`/`claimed_at`, and protects stage updates with the worker claim so a
late worker cannot release or complete another worker's lease.

### Stale claim recovery

Each layer claim resets stale rows in the requested claim stage back to
`pending` when `claimed_at` is older than `CLAIM_LEASE_SECONDS`. Workers
heartbeat active claims while processing and release in-flight claims on
SIGTERM. The current defaults use a 15-minute claim lease with a 60-second
heartbeat.

## Work Breakdown

### Layer (Rust)

| # | Task | Scope |
|---|------|-------|
| L1 | Add `sqlx` + PostgreSQL connection pool to layer-gateway | `src/config.rs`, `src/main.rs`, `Cargo.toml` |
| L2 | Migrations infrastructure (embedded migrations via sqlx) | `migrations/` dir |
| L3 | Create `pipelines` and `pipeline_documents` tables | migration SQL |
| L4 | `POST /v2/pipelines` — create pipeline | new `src/pipeline.rs` |
| L5 | `GET /v2/pipelines/{id}/status` — stage counts | `src/pipeline.rs` |
| L6 | `PUT /v2/pipelines/{id}/documents/{doc_id}` — stage chunks | writes to Aerospike + PG |
| L7 | `GET /v2/pipelines/{id}/documents/{doc_id}/chunks` — read chunks | reads from Aerospike |
| L8 | `PUT /v2/pipelines/{id}/documents/{doc_id}/vectors` — write vectors or error | upserts to Turbopuffer + PG state |
| L9 | `POST /v2/pipelines/{id}/claim` — atomic claim | `SELECT FOR UPDATE SKIP LOCKED` |
| L10 | Stale claim recovery (background task) | tokio spawn, runs every 60s |
| L11 | Add PostgreSQL to layer Helm chart | `templates/postgres-statefulset.yaml`, values |
| L12 | Add PVC template to layer Helm chart | `templates/pvc.yaml`, 100Gi |

### hev-shop indexer (Python)

| # | Task | Scope |
|---|------|-------|
| S1 | FastAPI app skeleton, config, Dockerfile | `indexer/app/main.py`, `Dockerfile` |
| S2 | Dataset manager — stream/cache HF metadata to PVC | `indexer/app/dataset.py` |
| S3 | `POST /index` endpoint — accepts count + category | `indexer/app/main.py` |
| S4 | CPU extraction worker — parse metadata, download images, stage to layer | `indexer/app/extraction.py` |
| S5 | GPU embedding worker — claim docs through layer, load images, CLIP encode, write vectors | `indexer/app/embedding.py` |
| S6 | `GET /status` endpoint — proxy pipeline status from layer | `indexer/app/main.py` |
| S7 | Layer pipeline client (Python) | `hevlayer` SDK (`hev/layer/clients/python`) |
| S8 | Kubernetes manifests for API, CPU workers, GPU workers, PVC | `kubernetes/` |
| S9 | KEDA ScaledObjects for CPU and GPU workers | `kubernetes/` |

### hev-shop CLI (Go) — phase 2 additions

| # | Task | Scope |
|---|------|-------|
| C1 | `hev-shop index` — calls indexer `POST /index` | `cmd/index.go` |
| C2 | `hev-shop search --image <path>` — CLIP search via CLI | `cmd/search.go` (future) |

## Infrastructure

### Shared PVC

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: hev-shop-data
  namespace: hev-shop
spec:
  accessModes: [ReadWriteMany]   # shared across CPU + GPU pods
  storageClassName: efs-sc        # EFS for RWX on EKS
  resources:
    requests:
      storage: 100Gi
```

Mounts at `/data` in both CPU and GPU pods:
- `/data/dataset/` — HF parquet files (~2-5GB for Electronics metadata)
- `/data/images/` — downloaded product images (~50-100GB at scale)

### KEDA

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: hev-shop-gpu-scaler
spec:
  scaleTargetRef:
    name: hev-shop-gpu-worker
  minReplicaCount: 0
  maxReplicaCount: 2
  cooldownPeriod: 300
  pollingInterval: 30
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://layer-gateway.layer.svc.cluster.local:8080/v2/metrics
        metricName: hev_shop_product_embedding_docs
        query: 'sum(layer_pipeline_stage_count{pipeline_id="hev-shop-product-images",stage=~"pending|embedding"}) or vector(0)'
        threshold: "10000"
```

Production-scale load tests should use 10k extraction jobs and 10k Turbopuffer
upsert requests. The embedding worker claims smaller 2k document batches,
encodes images in `EMBEDDING_BATCH_SIZE` micro-batches to fit GPU/CPU memory,
then sends accumulated vectors in namespace upserts and marks the claimed
pipeline documents indexed through layer-gateway.

## Ordering

Layer work (L1-L12) unblocks indexer work (S4-S9). Can be parallelized:
- **Layer track:** L1 → L2 → L3 → L4-L10 (pipeline API) → L11-L12 (Helm)
- **Indexer track:** S1 → S2 → S7 → S3 (can start with mocked layer) → S4-S5 (needs L4-L9) → S8-S9
- **Immediately parallel:** S1-S2 (indexer skeleton + dataset) alongside L1-L3 (postgres in layer)

## Open for Future Phases

- Text embedding pipeline (reviews, descriptions) → same `amazon-products` namespace, different vector field
- `POST /index { count: -1 }` for full category indexing
- Multi-category support (run multiple pipelines)
- Search endpoint in indexer for CLIP text-to-image queries
