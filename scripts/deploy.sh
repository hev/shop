#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-hev-shop}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
BUILD_IMAGE="${BUILD_IMAGE:-1}"
BUILD_WEB="${BUILD_WEB:-0}"
BUILDER="${BUILDER:-depot}"
AWS_REGION="${AWS_REGION:-us-east-1}"
TF_DIR="${TF_DIR:-}"
KEDA_NAMESPACE="${KEDA_NAMESPACE:-keda}"
KEDA_NODE_ROLE="${KEDA_NODE_ROLE:-infra}"
OPENROUTER_OP_VAULT="${OPENROUTER_OP_VAULT:-mesh-staging}"
OPENROUTER_OP_ITEM="${OPENROUTER_OP_ITEM:-layer-openrouter}"
OPENROUTER_OP_FIELD="${OPENROUTER_OP_FIELD:-credential}"
OP_ACCOUNT="${OP_ACCOUNT:-}"

log() { echo "==> $*"; }
err() { echo "ERROR: $*" >&2; exit 1; }
require_tool() {
  command -v "$1" >/dev/null 2>&1 || err "Missing required tool: $1"
}

for arg in "$@"; do
  case "$arg" in
    --skip-build) BUILD_IMAGE=0 ;;
    --build-web) BUILD_WEB=1 ;;
    *) err "Unknown argument: $arg" ;;
  esac
done

require_tool kubectl
require_tool aws

if [[ -n "$TF_DIR" && -d "$TF_DIR" ]]; then
  pushd "$TF_DIR" >/dev/null
  ECR_REPOSITORY_URL="${ECR_REPOSITORY_URL:-$(terraform output -raw ecr_amazon_reviews_url 2>/dev/null || true)}"
  ECR_WEB_URL="${ECR_WEB_URL:-$(terraform output -raw ecr_hev_shop_web_url 2>/dev/null || true)}"
  CLUSTER_NAME="${CLUSTER_NAME:-$(terraform output -raw cluster_name 2>/dev/null || true)}"
  HEV_SHOP_EFS_FILE_SYSTEM_ID="${HEV_SHOP_EFS_FILE_SYSTEM_ID:-$(terraform output -raw hev_shop_efs_file_system_id 2>/dev/null || true)}"
  popd >/dev/null
else
  ECR_REPOSITORY_URL="${ECR_REPOSITORY_URL:-}"
  ECR_WEB_URL="${ECR_WEB_URL:-}"
  CLUSTER_NAME="${CLUSTER_NAME:-}"
  HEV_SHOP_EFS_FILE_SYSTEM_ID="${HEV_SHOP_EFS_FILE_SYSTEM_ID:-}"
fi

[[ -n "$ECR_REPOSITORY_URL" ]] || err "Set ECR_REPOSITORY_URL or apply Terraform with ecr_amazon_reviews_url output."
[[ -n "$CLUSTER_NAME" ]] || err "Set CLUSTER_NAME or apply Terraform with cluster_name output."
[[ -n "$HEV_SHOP_EFS_FILE_SYSTEM_ID" ]] || err "Set HEV_SHOP_EFS_FILE_SYSTEM_ID or apply Terraform with hev_shop_efs_file_system_id output."
if [[ "$BUILD_WEB" == "1" ]]; then
  [[ -n "$ECR_WEB_URL" ]] || err "Set ECR_WEB_URL or apply Terraform with ecr_hev_shop_web_url output."
fi

IMAGE="${ECR_REPOSITORY_URL}:${IMAGE_TAG}"
WEB_IMAGE="${ECR_WEB_URL:+${ECR_WEB_URL}:${IMAGE_TAG}}"

log "Updating kubeconfig for ${CLUSTER_NAME}..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"

if ! kubectl get crd scaledobjects.keda.sh >/dev/null 2>&1; then
  require_tool helm
  log "KEDA is not installed; installing it on mesh-role=${KEDA_NODE_ROLE} nodes..."
  helm repo add kedacore https://kedacore.github.io/charts >/dev/null 2>&1 || true
  helm repo update kedacore
  helm upgrade --install keda kedacore/keda \
    -n "$KEDA_NAMESPACE" --create-namespace \
    --set "nodeSelector.mesh-role=${KEDA_NODE_ROLE}" \
    --set 'tolerations[0].key=mesh-role' \
    --set 'tolerations[0].operator=Equal' \
    --set "tolerations[0].value=${KEDA_NODE_ROLE}" \
    --set 'tolerations[0].effect=NoSchedule'
  kubectl rollout status deployment/keda-operator -n "$KEDA_NAMESPACE" --timeout=180s
  kubectl rollout status deployment/keda-operator-metrics-apiserver -n "$KEDA_NAMESPACE" --timeout=180s
  kubectl rollout status deployment/keda-admission-webhooks -n "$KEDA_NAMESPACE" --timeout=180s
fi

if [[ "$BUILD_IMAGE" == "1" || "$BUILD_WEB" == "1" ]]; then
  log "Logging in to ECR..."
  ECR_LOGIN_URL="${ECR_REPOSITORY_URL:-$ECR_WEB_URL}"
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "${ECR_LOGIN_URL%/*}"
fi

if [[ "$BUILD_IMAGE" == "1" ]]; then
  log "Building and pushing ${IMAGE}..."
  case "$BUILDER" in
    depot)
      require_tool depot
      DEPOT_DISABLE_OTEL=1 depot build --platform linux/amd64 \
        -f indexer/Dockerfile -t "$IMAGE" --push .
      ;;
    docker)
      require_tool docker
      docker buildx build --platform linux/amd64 \
        -f indexer/Dockerfile -t "$IMAGE" --push .
      ;;
    *)
      err "Unsupported BUILDER=${BUILDER}; use depot or docker."
      ;;
  esac
fi

if [[ "$BUILD_WEB" == "1" ]]; then
  log "Building and pushing ${WEB_IMAGE}..."
  case "$BUILDER" in
    depot)
      require_tool depot
      DEPOT_DISABLE_OTEL=1 depot build --platform linux/amd64 \
        -f web/Dockerfile -t "$WEB_IMAGE" --push web
      ;;
    docker)
      require_tool docker
      docker buildx build --platform linux/amd64 \
        -f web/Dockerfile -t "$WEB_IMAGE" --push web
      ;;
    *)
      err "Unsupported BUILDER=${BUILDER}; use depot or docker."
      ;;
  esac
fi

log "Applying hev-shop EFS StorageClass for ${HEV_SHOP_EFS_FILE_SYSTEM_ID}..."
kubectl apply -f - <<EOF
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: hev-shop-efs
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: ${HEV_SHOP_EFS_FILE_SYSTEM_ID}
  directoryPerms: "777"
  basePath: "/hev-shop"
reclaimPolicy: Delete
volumeBindingMode: Immediate
mountOptions:
  - tls
EOF

CURRENT_WEB_IMAGE=""
if [[ "$BUILD_WEB" != "1" ]]; then
  CURRENT_WEB_IMAGE="$(kubectl get deployment/hev-shop-web -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[?(@.name=="web")].image}' 2>/dev/null || true)"
fi

log "Applying hev-shop manifests..."
kubectl apply -k kubernetes

OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
if [[ -z "$OPENROUTER_API_KEY" ]] && command -v op >/dev/null 2>&1; then
  OP_ARGS=()
  if [[ -n "$OP_ACCOUNT" ]]; then
    OP_ARGS=(--account "$OP_ACCOUNT")
  fi
  OPENROUTER_API_KEY="$(op read "op://${OPENROUTER_OP_VAULT}/${OPENROUTER_OP_ITEM}/${OPENROUTER_OP_FIELD}" ${OP_ARGS[@]+"${OP_ARGS[@]}"} 2>/dev/null || true)"
fi
if [[ -n "$OPENROUTER_API_KEY" ]]; then
  log "Restoring OpenRouter API key into ${NAMESPACE}/hev-shop-secrets..."
  OPENROUTER_API_KEY_B64="$(printf '%s' "$OPENROUTER_API_KEY" | base64 | tr -d '\n')"
  kubectl patch secret hev-shop-secrets -n "$NAMESPACE" \
    --type merge \
    -p "{\"data\":{\"OPENROUTER_API_KEY\":\"${OPENROUTER_API_KEY_B64}\"}}" >/dev/null
else
  log "OpenRouter API key not supplied or found; review-classify workers will idle."
fi

if [[ "$BUILD_WEB" != "1" && -n "$CURRENT_WEB_IMAGE" ]]; then
  log "Restoring web image to ${CURRENT_WEB_IMAGE}..."
  kubectl set image deployment/hev-shop-web "web=${CURRENT_WEB_IMAGE}" -n "$NAMESPACE"
fi

log "Waiting for shared data PVC..."
kubectl wait --for=jsonpath='{.status.phase}'=Bound pvc/hev-shop-data -n "$NAMESPACE" --timeout=180s

log "Setting image to ${IMAGE}..."
kubectl set image deployment/hev-shop-api "api=${IMAGE}" -n "$NAMESPACE"
kubectl set image deployment/hev-shop-cpu-worker "worker=${IMAGE}" -n "$NAMESPACE"
kubectl set image deployment/hev-shop-gpu-worker "worker=${IMAGE}" -n "$NAMESPACE"
kubectl set image deployment/hev-shop-review-embed-worker "worker=${IMAGE}" -n "$NAMESPACE"
kubectl set image deployment/hev-shop-review-classify-worker "worker=${IMAGE}" -n "$NAMESPACE"
kubectl set image deployment/hev-shop-review-aggregate-worker "worker=${IMAGE}" -n "$NAMESPACE"

log "Restarting deployments to pull ${IMAGE}..."
kubectl rollout restart \
  deployment/hev-shop-api \
  deployment/hev-shop-cpu-worker \
  deployment/hev-shop-gpu-worker \
  deployment/hev-shop-review-embed-worker \
  deployment/hev-shop-review-classify-worker \
  deployment/hev-shop-review-aggregate-worker \
  -n "$NAMESPACE"

log "Waiting for API rollout..."
kubectl rollout status deployment/hev-shop-api -n "$NAMESPACE" --timeout=180s

if [[ "$BUILD_WEB" == "1" ]]; then
  log "Setting web image to ${WEB_IMAGE}..."
  kubectl set image deployment/hev-shop-web "web=${WEB_IMAGE}" -n "$NAMESPACE"
  kubectl rollout restart deployment/hev-shop-web -n "$NAMESPACE"
  kubectl rollout status deployment/hev-shop-web -n "$NAMESPACE" --timeout=180s

  WEB_LB="$(kubectl get svc hev-shop-web -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  if [[ -n "$WEB_LB" ]]; then
    log "Web reachable at http://${WEB_LB}"
  else
    log "Web NLB not yet provisioned. Watch with:"
    log "  kubectl get svc hev-shop-web -n ${NAMESPACE} -w"
  fi
fi

if [[ "$NAMESPACE" != "layer" ]] && kubectl get deployment/hev-shop-api -n layer >/dev/null 2>&1; then
  log "Legacy hev-shop workloads still exist in layer namespace."
  log "Remove them after validating this deploy with:"
  log "  kubectl delete deploy,svc,cm,secret,scaledobject -n layer -l app.kubernetes.io/name=hev-shop"
fi

log "hev-shop deployed. Port-forward with:"
log "  kubectl port-forward svc/hev-shop-api 8090:8080 -n ${NAMESPACE}"
