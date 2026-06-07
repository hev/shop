# Layer CRDs

Keep app-owned Layer Pipeline/UDF YAML in this directory when hev-shop moves a
pipeline from SDK registration to declarative operator ownership.

There are no active CRDs today. The product and extraction queues are still
created by the indexer with the Layer SDK:

- `indexer/app/main.py` ensures `PIPELINE_ID` and `EXTRACTION_PIPELINE_ID`
  before staging extraction jobs.
- `indexer/app/worker.py` ensures the extraction queue for `WORKER_TYPE=cpu`.
- `indexer/app/pipeline.py` ensures the product queue for `WORKER_TYPE=gpu`.

Do not put app-owned Pipeline/UDF manifests under `helm/hev-shop/templates/`.
The Helm chart should deploy Kubernetes workloads and pass IDs/config only; the
pipeline shape belongs with the indexer code that owns it.
