# hev-shop Helm Chart

This chart deploys the full hev-shop app:

- indexer API
- Next.js web storefront
- CPU extraction worker
- GPU product image embedding worker
- KEDA ScaledObjects backed by Layer pipeline metrics
- optional Karpenter EC2NodeClasses and NodePools for CPU/GPU workers
- shared RWX PVC for dataset cache

The chart assumes Layer already provides the gateway and a Prometheus-compatible
query API for gateway metrics.
By default it uses:

```text
http://layer-gateway.layer.svc.cluster.local:8080
http://layer-gateway.layer.svc.cluster.local:8080/v2/metrics
```

Install:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace
```

Use an existing secret:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace \
  --set secrets.create=false \
  --set secrets.existingSecret=hev-shop-secrets
```

The secret is only for app credentials such as the HuggingFace token and Layer
gateway API key; hev-shop does not need Layer PostgreSQL credentials.

## Karpenter NodePools

The chart can also own the app's Karpenter capacity. This keeps node scaling
with the workload whose KEDA ScaledObjects create pod demand from Layer
pipeline metrics.

Karpenter and its CRDs must already be installed. Enable the app NodePools with:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace \
  --set karpenter.enabled=true \
  --set karpenter.clusterName=<eks-cluster-name> \
  --set karpenter.kubernetesVersion=<eks-version> \
  --set karpenter.nodeInstanceProfile=<karpenter-node-instance-profile>
```

Defaults:

- CPU NodePool: `mesh-role=app`, on-demand `c`/`m` instances, `32` CPU limit.
- GPU NodePool: `mesh-role=gpu`, `g4dn`/`g5` spot or on-demand instances,
  `32` CPU limit.

Override `karpenter.cpu` or `karpenter.gpu` in `values.yaml` to change labels,
taints, requirements, limits, or disruption policy.
