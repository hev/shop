# hev-shop Helm Chart

This chart deploys the full hev-shop app:

- indexer API
- Next.js web storefront
- CPU extraction worker
- GPU product image embedding worker
- GPU review embedding worker
- CPU review classification worker
- CPU review aggregation worker
- KEDA ScaledObjects backed by Layer PostgreSQL
- shared RWX PVC for dataset, image, and model caches

The chart assumes Layer already provides the gateway and PostgreSQL services.
By default it uses:

```text
http://layer-gateway.layer.svc.cluster.local:8080
postgres://hevlayer:hevlayer@layer-postgres.layer.svc.cluster.local:5432/hevlayer
```

Install:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace
```

Use a managed Layer PostgreSQL URL:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace \
  --set-string layer.databaseUrl='postgres://user:pass@host:5432/hevlayer'
```

Use an existing secret:

```sh
helm upgrade --install hev-shop ./helm/hev-shop \
  --namespace hev-shop \
  --create-namespace \
  --set secrets.create=false \
  --set secrets.existingSecret=hev-shop-secrets
```

The secret must provide `LAYER_DATABASE_URL`; KEDA reads it through
`connectionFromEnv`.
