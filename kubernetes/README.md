# hev-shop Kubernetes

The standalone deploy path is the Helm chart in `helm/hev-shop`. These raw
manifests are kept for low-level inspection and kustomize-based operations.

These manifests run the hev-shop indexer in its own `hev-shop` namespace. It
talks to platform services in the `layer` namespace by fully qualified service
DNS names:

- `hev-shop-api` exposes `POST /index`, `GET /status`, and `POST /search`
- `hev-shop-cpu-worker` is KEDA-scaled from queued extraction jobs in PostgreSQL
- `hev-shop-gpu-worker` is KEDA-scaled from pending layer pipeline documents and
  writes CLIP image vectors to Turbopuffer through layer-gateway
- `hev-shop-review-embed-worker` chunks reviews and writes Qwen text vectors to
  `amazon-reviews-*` shards
- `hev-shop-review-classify-worker` classifies reviews through OpenRouter and
  writes `review_tags`
- `hev-shop-review-aggregate-worker` rolls review tags back onto product attrs
- `hev-shop-web` is the Next.js storefront. It reaches the API at
  `HEV_SHOP_API_BASE=http://hev-shop-api.hev-shop.svc.cluster.local:8080` and
  is exposed publicly via an AWS NLB (`Service type=LoadBalancer`, no DNS, no TLS).
  Grab the hostname with:
  ```bash
  kubectl get svc hev-shop-web -n hev-shop \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
  ```

Prerequisites:

- Layer gateway deployed in `layer` with PostgreSQL enabled and
  `TURBOPUFFER_API_KEY`
- KEDA installed in the cluster
- AWS EFS CSI driver installed, plus a `hev-shop-efs` StorageClass pointing at
  the Terraform-managed hev-shop EFS filesystem
- Karpenter NodePools installed for `mesh-role=app` CPU workers and
  `mesh-role=gpu` GPU workers
- `OPENROUTER_API_KEY` set in `hev-shop-secrets` before enabling
  `review-classify` or review backfills

Build and deploy:

```bash
scripts/deploy.sh             # indexer + workers only
scripts/deploy.sh --build-web # also build/push the storefront image
```

`--build-web` builds `web/Dockerfile` and pushes to the
`hev-shop-web` ECR repo (output `ecr_hev_shop_web_url`). The Next.js
deployment is only `kubectl set image`'d when this flag is on, so the
first storefront deploy must include it.

For a private registry or ECR image, update `kustomization.yaml` or run:

```bash
kubectl set image deployment/hev-shop-api api=$IMAGE -n hev-shop
kubectl set image deployment/hev-shop-cpu-worker worker=$IMAGE -n hev-shop
kubectl set image deployment/hev-shop-gpu-worker worker=$IMAGE -n hev-shop
kubectl set image deployment/hev-shop-review-embed-worker worker=$IMAGE -n hev-shop
kubectl set image deployment/hev-shop-review-classify-worker worker=$IMAGE -n hev-shop
kubectl set image deployment/hev-shop-review-aggregate-worker worker=$IMAGE -n hev-shop
kubectl rollout restart deployment/hev-shop-api deployment/hev-shop-cpu-worker deployment/hev-shop-gpu-worker deployment/hev-shop-review-embed-worker deployment/hev-shop-review-classify-worker deployment/hev-shop-review-aggregate-worker -n hev-shop
```

Queue a production-sized smoke run and watch scaling:

```bash
kubectl port-forward svc/hev-shop-api 8090:8080 -n hev-shop
curl -X POST http://localhost:8090/index \
  -H 'content-type: application/json' \
  -d '{"count": 100000, "category": "Electronics", "job_size": 10000}'

scripts/watch-scaling.sh
```

Queue a richer multi-category scale run through the deployed API:

```bash
scripts/queue-scale-run.sh
```

The helper defaults to 50k products in each of eight categories (400k total
requested products, split into 10k-product extraction jobs). Override with
`COUNT_PER_CATEGORY`, `JOB_SIZE`, or `CATEGORIES`:

```bash
COUNT_PER_CATEGORY=25000 \
CATEGORIES='Electronics,Home and Kitchen,Books,Toys and Games' \
scripts/queue-scale-run.sh
```

Production-like defaults use 10k product extraction jobs, 2k GPU embedding
claims, and up to 10k Turbopuffer vector upserts. CLIP encoding still happens in
smaller micro-batches inside each worker to fit local GPU/CPU memory. The GPU
worker scaler is capped at 2 replicas for the current `mesh-bench` quota.

See `SCALING.md` for the 100k smoke-run notes and current
Karpenter behavior.

The default product GPU scaler watches pipeline `amazon-products-images`.
Review scalers watch `hev-shop-reviews` work-item prefixes and
`amazon-products-review-tags`. If you submit different pipeline IDs, update the
matching ConfigMap values and ScaledObject queries together.
