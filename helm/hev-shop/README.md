# hev-shop Helm Chart

This chart deploys the always-on hev-shop pods:

- search read API
- indexer API
- Next.js web storefront
- optional Karpenter EC2NodeClasses and NodePools for CPU/GPU worker capacity
- shared RWX PVC

The CPU extraction and GPU embedding workers are *not* chart-owned: they are
Layer `Pipeline` resources under `indexer/pipelines/`, reconciled by the Layer
operator into Deployments + KEDA ScaledObjects. Apply them after the chart:

```sh
kubectl apply -f indexer/pipelines/
```

The chart assumes Layer already provides the gateway, by default at:

```text
http://layer-gateway.layer.svc.cluster.local:8080
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
with the workload whose Pipeline resources create pod demand from Layer
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
