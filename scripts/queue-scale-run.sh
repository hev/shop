#!/usr/bin/env bash
set -euo pipefail

APP_NAMESPACE="${APP_NAMESPACE:-hev-shop}"
PIPELINE_ID="${PIPELINE_ID:-hev-shop-product-images}"
TARGET_NAMESPACE="${TARGET_NAMESPACE:-amazon-products}"
COUNT_PER_CATEGORY="${COUNT_PER_CATEGORY:-50000}"
JOB_SIZE="${JOB_SIZE:-10000}"
CATEGORIES="${CATEGORIES:-Electronics,Home and Kitchen,Clothing Shoes and Jewelry,Sports and Outdoors,Tools and Home Improvement,Toys and Games,Beauty and Personal Care,Books}"

echo "Queueing hev-shop scale run"
echo "  app namespace:      ${APP_NAMESPACE}"
echo "  pipeline:           ${PIPELINE_ID}"
echo "  target namespace:   ${TARGET_NAMESPACE}"
echo "  count per category: ${COUNT_PER_CATEGORY}"
echo "  job size:           ${JOB_SIZE}"
echo "  categories:         ${CATEGORIES}"

kubectl exec -i -n "$APP_NAMESPACE" deploy/hev-shop-api -- \
  python - "$COUNT_PER_CATEGORY" "$JOB_SIZE" "$PIPELINE_ID" "$TARGET_NAMESPACE" "$CATEGORIES" <<'PY'
import json
import sys
import urllib.error
import urllib.request

count = int(sys.argv[1])
job_size = int(sys.argv[2])
pipeline_id = sys.argv[3]
namespace = sys.argv[4]
categories = [category.strip() for category in sys.argv[5].split(",") if category.strip()]

responses = []
for category in categories:
    payload = {
        "count": count,
        "category": category,
        "pipeline_id": pipeline_id,
        "namespace": namespace,
        "job_size": job_size,
    }
    request = urllib.request.Request(
        "http://127.0.0.1:8080/index",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            responses.append(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        sys.stderr.write(exc.read().decode("utf-8"))
        raise

print(
    json.dumps(
        {
            "pipeline_id": pipeline_id,
            "namespace": namespace,
            "count_per_category": count,
            "jobs_created": sum(response.get("jobs_created", 0) for response in responses),
            "categories": responses,
        },
        indent=2,
    )
)
PY

echo
echo "Watch scaling with:"
echo "  APP_NAMESPACE=${APP_NAMESPACE} PIPELINE_ID=${PIPELINE_ID} scripts/watch-scaling.sh"

if [[ "${WATCH:-0}" == "1" ]]; then
  APP_NAMESPACE="$APP_NAMESPACE" PIPELINE_ID="$PIPELINE_ID" scripts/watch-scaling.sh
fi
