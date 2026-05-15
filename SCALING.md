# hev-shop Scaling Notes

## Production-Scale Defaults

- Extraction jobs default to 10,000 products per job.
- GPU workers claim up to 2,000 pending pipeline documents per outer batch.
- CLIP inference still runs in smaller `EMBEDDING_BATCH_SIZE` micro-batches to fit
  device memory.
- Vector writes use `POST /v2/namespaces/{namespace}` with up to 10,000 upserts
  per request, then call layer-gateway to mark the claimed pipeline documents
  indexed.
- layer-gateway raises its request body limit to support large JSON vector
  batches.
- Pipeline workers claim, heartbeat, release, fail, and complete documents
  through layer-gateway. Workers heartbeat active claims every 60 seconds.
  Stale claims recover after 15 minutes, and SIGTERM releases in-flight
  extraction and pipeline claims before pod shutdown.
- The default GPU scaler is capped at 2 replicas. That matches the current
  `mesh-bench` GPU quota envelope and avoids futile third-node launches.
- Karpenter consolidates hev-shop worker nodes only when they are empty for 10
  minutes, so long-running worker pods are not disrupted for underutilization.

## GPU Image Bake-In Plan

Current GPU cold start pulls a multi-GB worker image and then warms model cache
from `/data/models`. To reduce scale-up latency:

- Build a dedicated GPU worker image that pre-downloads CLIP/Qwen model weights
  into the image or into a mounted EBS snapshot.
- Publish the baked image alongside the regular indexer image and point
  `hev-shop-gpu-worker` at it.
- Optionally use a custom Karpenter GPU AMI with the baked image pre-pulled and
  NVIDIA runtime validation already complete.
- Keep `/data/models` as a writable fallback cache for model upgrades.

## Watch Command

```bash
scripts/watch-scaling.sh
```

Useful overrides:

```bash
APP_NAMESPACE=hev-shop PIPELINE_ID=amazon-products-images INTERVAL_SECONDS=10 \
  scripts/watch-scaling.sh
```

## Multi-Category Scale Run

Queue a richer dataset for autoscaling tests:

```bash
scripts/queue-scale-run.sh
```

Defaults:

- 50,000 requested products per category
- 8 categories: Electronics, Home and Kitchen, Clothing Shoes and Jewelry,
  Sports and Outdoors, Tools and Home Improvement, Toys and Games, Beauty and
  Personal Care, Books
- 10,000 products per extraction job, producing 40 queued CPU jobs total

Useful overrides:

```bash
COUNT_PER_CATEGORY=25000 \
JOB_SIZE=5000 \
CATEGORIES='Electronics,Home and Kitchen,Books,Toys and Games' \
scripts/queue-scale-run.sh
```

## 400k Multi-Category Run: 2026-05-13

Queued with the default helper settings:

```text
COUNT_PER_CATEGORY=50000
JOB_SIZE=10000
CATEGORIES=Electronics,Home and Kitchen,Clothing Shoes and Jewelry,Sports and Outdoors,Tools and Home Improvement,Toys and Games,Beauty and Personal Care,Books
```

Result:

- API created 40 extraction jobs across 8 categories.
- CPU KEDA became Active and scaled `hev-shop-cpu-worker` to the configured max
  of 8 replicas.
- Karpenter provisioned additional `hev-shop-cpu` nodes and one underutilized
  CPU node was consolidated while the workload kept running.
- GPU KEDA became Active, scaled desired GPU replicas to 3, and Karpenter
  provisioned two `g4dn.xlarge` GPU nodes: one Spot and one On-Demand.
- The third GPU pod remained Pending because EC2 GPU capacity/quota blocked
  additional `g4dn` capacity. Events included `VcpuLimitExceeded`,
  `MaxSpotInstanceCountExceeded`, and `NoCompatibleInstanceTypes`.
- Follow-up applied after the checkpoint: GPU max replicas is now 2, CPU KEDA
  targets 2 extraction jobs per pod, and both hev-shop NodePools use
  `consolidationPolicy: WhenEmpty` with `consolidateAfter: 10m`.

Checkpoint:

```json
{"pipeline_id":"amazon-products-images","layer":{"counts":{"embedding":20000,"pending":6424},"pending_count":6424},"jobs":{"succeeded":3,"queued":29,"running":9}}
```

Kubernetes state at the checkpoint:

```text
hev-shop-cpu-worker READY 8 REPLICAS 8
hev-shop-gpu-worker READY 2 REPLICAS 3

keda-hpa-hev-shop-cpu-worker REPLICAS 8
keda-hpa-hev-shop-gpu-worker REPLICAS 3
```

## 100k Smoke Run: 2026-05-12

Queued:

```json
{"count":100000,"category":"Electronics","pipeline_id":"amazon-products-images","job_size":10000}
```

Initial result:

- API created 10 extraction jobs.
- CPU KEDA ScaledObject became Active and HPA drove desired replicas to the
  configured max of 8. The scaler now counts queued, retry, and running jobs so
  claimed work keeps workers alive.
- GPU KEDA ScaledObject became Active as soon as CPU workers staged pending
  pipeline documents and scaled from 0 to 1. The scaler now counts pending and
  embedding documents so claimed embedding batches keep workers alive.
- `layer` and `hev-shop` are separated: application workloads run in
  `hev-shop`; platform gateway and PostgreSQL remain in `layer`.
- `mesh-postgres` is no longer rendered by the mesh Helm chart; only
  `layer-postgres` remains for pipeline state.

Original cluster bottleneck:

- The current `mesh-bench` cluster has one schedulable `mesh-role=infra` node
  with about 1930m allocatable CPU.
- CPU worker HPA requested 8 replicas, but only one CPU worker scheduled. The
  other CPU worker pods were Pending with:
  `0/2 nodes are available: 1 Insufficient cpu, 1 node(s) had untolerated taint(s)`.
- This is now handled by the Karpenter `hev-shop-cpu` NodePool. The earlier
  bottleneck was fixed by moving CPU workers off the fixed `mesh-role=infra`
  node and onto dynamically provisioned app nodes.

Representative watch output:

```text
hev-shop-cpu-worker   READY 1   REPLICAS 8
hev-shop-gpu-worker   READY 1   REPLICAS 1

hev-shop-cpu-worker ScaledObject READY=True ACTIVE=True MAX=8
hev-shop-gpu-worker ScaledObject READY=True ACTIVE=True MAX=2

keda-hpa-hev-shop-cpu-worker  TARGETS 1125m/1  REPLICAS 8
keda-hpa-hev-shop-gpu-worker  TARGETS 197/10k  REPLICAS 1
```

Current checkpoint before committing progress:

```json
{"pipeline_id":"amazon-products-images","layer":{"counts":{"pending":6693},"pending_count":6693},"jobs":{"queued":9,"running":1,"succeeded":3}}
```

Kubernetes state at the original checkpoint:

- `hev-shop-api`: 1/1 available.
- `hev-shop-cpu-worker`: desired 8, available 1; remaining pods Pending due
  infra-node CPU capacity.
- `hev-shop-gpu-worker`: desired 1, available 1; HPA target around `6681/10k`.
- GPU logs show the worker actively fetching staged chunks from
  `layer-gateway.layer.svc.cluster.local`.

## Karpenter + EFS Checkpoint: 2026-05-12

- Terraform now provisions a shared EFS filesystem, mount targets in both
  private subnets, and the AWS EFS CSI add-on.
- hev-shop mounts `/data` from the `hev-shop-data` RWX PVC instead of node-local
  hostPath storage.
- `hev-shop-cpu-worker` runs on the Karpenter `hev-shop-cpu` NodePool with
  `mesh-role=app`; KEDA scaled it to 8 real workers and Karpenter launched app
  nodes for them.
- `hev-shop-gpu-worker` requests `nvidia.com/gpu: "1"` and targets
  `mesh-role=gpu`. A one-pod GPU smoke test launched a Spot `g4dn.xlarge`,
  initialized the NVIDIA device plugin, ran the pod, and consolidated the GPU
  NodePool back to zero after deletion.
- `hev-shop-gpu` is currently at `NODES=0`, which is the desired idle state.
- Current us-east-1 G/VT quotas are `4` vCPU for On-Demand and `4` vCPU for Spot,
  enough for the current two-GPU operating envelope when one node lands on Spot
  and one on On-Demand.
