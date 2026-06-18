# Layer UDFs (Functions)

Home for app-owned Layer `Function` resources, the sibling of the `Pipeline`
resources in `../pipelines/`. The first is `trending.yaml` (RFC 0040; see
`../../docs/TRENDING_DESIGN.md`) — a scheduled *reduce* over search-history,
backed by the Layer Function `schedule` trigger.

A `Function` (UDF) is the declarative surface for derived/enrichment work that
runs *over indexed namespaces* rather than a staged ingest queue: it's
triggered by document discovery or writes, reads existing vectors/attributes,
and writes derived results back. Use it when the work reacts to what's already
indexed (e.g. backfilling an attribute, recomputing a derived field) instead of
draining a pipeline stage.

Same ownership split as pipelines (see `../../CLAUDE.md` → Pipeline Authoring):
the Layer operator reconciles the `Function` into a worker Deployment + scaling;
the worker is a plain script driven by operator-injected env. The Helm chart
carries no Function shape.

Apply alongside the pipelines:

```sh
kubectl apply -f indexer/udfs/
```

Sketch of the resource (see https://hevlayer.com/docs/kubernetes for the full
field reference):

```yaml
apiVersion: hevlayer.com/v1alpha1
kind: Function
metadata:
  name: hev-shop-<name>
  namespace: hev-shop
spec:
  targetNamespaces: [amazon-products]
  triggers: [discovery]          # discovery | write | schedule
  worker:
    image: 186219257916.dkr.ecr.us-east-1.amazonaws.com/hev-shop-indexer:latest-<name>
  scaling:
    pool: cpu                     # must name a pool in InfraRules/default
    replicas:
      max: 4
```

If a Function needs its own worker code, add a stage script next to
`extract_chunk.py` / `embed.py` and a matching target in `../Dockerfile`.
