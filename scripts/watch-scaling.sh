#!/usr/bin/env bash
set -euo pipefail

APP_NAMESPACE="${APP_NAMESPACE:-hev-shop}"
PIPELINE_ID="${PIPELINE_ID:-amazon-products-images}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-15}"

while true; do
  printf '\n== %s ==\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  echo "-- status"
  kubectl exec -n "$APP_NAMESPACE" deploy/hev-shop-api -- \
    python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/status?pipeline_id=${PIPELINE_ID}', timeout=10).read().decode())" \
    2>/dev/null || true

  echo "-- deployments"
  kubectl get deploy -n "$APP_NAMESPACE" \
    -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas,REPLICAS:.status.replicas,UPDATED:.status.updatedReplicas,AVAILABLE:.status.availableReplicas' \
    | grep -E 'NAME|hev-shop' || true

  echo "-- pods"
  kubectl get pods -n "$APP_NAMESPACE" -o wide | grep -E 'NAME|hev-shop' || true

  echo "-- scaledobjects"
  kubectl get scaledobject -n "$APP_NAMESPACE" || true

  echo "-- hpa"
  kubectl get hpa -n "$APP_NAMESPACE" || true

  sleep "$INTERVAL_SECONDS"
done
