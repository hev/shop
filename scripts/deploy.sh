#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

RELEASE="${RELEASE:-hev-shop}"
NAMESPACE="${NAMESPACE:-hev-shop}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
BUILD_INDEXER="${BUILD_INDEXER:-1}"
BUILD_SEARCH="${BUILD_SEARCH:-0}"
BUILD_WEB="${BUILD_WEB:-0}"
BUILDER="${BUILDER:-depot}"
AWS_REGION="${AWS_REGION:-us-east-1}"
TF_DIR="${TF_DIR:-../layer/infra/terraform}"
KEDA_NAMESPACE="${KEDA_NAMESPACE:-keda}"
KEDA_NODE_ROLE="${KEDA_NODE_ROLE:-system}"
LAYER_CLIENT_CONTEXT="${LAYER_CLIENT_CONTEXT:-../layer/clients/python}"
HELM_VALUES="${HELM_VALUES:-}"
HELM_SET="${HELM_SET:-}"

log() { echo "==> $*"; }
err() { echo "ERROR: $*" >&2; exit 1; }
require_tool() {
  command -v "$1" >/dev/null 2>&1 || err "Missing required tool: $1"
}

for arg in "$@"; do
  case "$arg" in
    --skip-build)
      BUILD_INDEXER=0
      BUILD_SEARCH=0
      BUILD_WEB=0
      ;;
    --build-indexer) BUILD_INDEXER=1 ;;
    --build-search) BUILD_SEARCH=1 ;;
    --build-web) BUILD_WEB=1 ;;
    *) err "Unknown argument: $arg" ;;
  esac
done

require_tool kubectl
require_tool helm
require_tool aws

INDEXER_IMAGE_REPOSITORY="${INDEXER_IMAGE_REPOSITORY:-${ECR_REPOSITORY_URL:-}}"
SEARCH_IMAGE_REPOSITORY="${SEARCH_IMAGE_REPOSITORY:-${ECR_SEARCH_URL:-}}"
WEB_IMAGE_REPOSITORY="${WEB_IMAGE_REPOSITORY:-${ECR_WEB_URL:-}}"
CLUSTER_NAME="${CLUSTER_NAME:-}"
HEV_SHOP_EFS_FILE_SYSTEM_ID="${HEV_SHOP_EFS_FILE_SYSTEM_ID:-}"

if [[ -n "$TF_DIR" && -d "$TF_DIR" ]]; then
  pushd "$TF_DIR" >/dev/null
  WEB_IMAGE_REPOSITORY="${WEB_IMAGE_REPOSITORY:-$(terraform output -raw ecr_hev_shop_web_url 2>/dev/null || true)}"
  CLUSTER_NAME="${CLUSTER_NAME:-$(terraform output -raw cluster_name 2>/dev/null || true)}"
  HEV_SHOP_EFS_FILE_SYSTEM_ID="${HEV_SHOP_EFS_FILE_SYSTEM_ID:-$(terraform output -raw hev_shop_efs_file_system_id 2>/dev/null || true)}"
  popd >/dev/null
fi

if [[ "$BUILD_INDEXER" == "1" ]]; then
  [[ -n "$INDEXER_IMAGE_REPOSITORY" ]] || err "Set INDEXER_IMAGE_REPOSITORY or ECR_REPOSITORY_URL to build the indexer image."
fi
if [[ "$BUILD_SEARCH" == "1" ]]; then
  [[ -n "$SEARCH_IMAGE_REPOSITORY" ]] || err "Set SEARCH_IMAGE_REPOSITORY or ECR_SEARCH_URL to build the search image."
fi
if [[ "$BUILD_WEB" == "1" ]]; then
  [[ -n "$WEB_IMAGE_REPOSITORY" ]] || err "Set WEB_IMAGE_REPOSITORY or ECR_WEB_URL to build the web image."
fi
[[ -n "$CLUSTER_NAME" ]] || err "Set CLUSTER_NAME or apply Terraform with cluster_name output."

log "Updating kubeconfig for ${CLUSTER_NAME}..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"

if ! kubectl get crd scaledobjects.keda.sh >/dev/null 2>&1; then
  log "KEDA is not installed; installing it on layer.hev.dev/node-role=${KEDA_NODE_ROLE} nodes..."
  helm repo add kedacore https://kedacore.github.io/charts >/dev/null 2>&1 || true
  helm repo update kedacore
  helm upgrade --install keda kedacore/keda \
    -n "$KEDA_NAMESPACE" --create-namespace \
    --set "nodeSelector.layer\\.hev\\.dev/node-role=${KEDA_NODE_ROLE}" \
    --set 'tolerations[0].key=layer.hev.dev/node-role' \
    --set 'tolerations[0].operator=Equal' \
    --set "tolerations[0].value=${KEDA_NODE_ROLE}" \
    --set 'tolerations[0].effect=NoSchedule'
  kubectl rollout status deployment/keda-operator -n "$KEDA_NAMESPACE" --timeout=180s
  kubectl rollout status deployment/keda-operator-metrics-apiserver -n "$KEDA_NAMESPACE" --timeout=180s
  kubectl rollout status deployment/keda-admission-webhooks -n "$KEDA_NAMESPACE" --timeout=180s
fi

docker_login() {
  local repository="$1"
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "${repository%/*}"
}

build_image() {
  local dockerfile="$1"
  local context="$2"
  local image="$3"
  shift 3

  log "Building and pushing ${image}..."
  case "$BUILDER" in
    depot)
      require_tool depot
      DEPOT_DISABLE_OTEL=1 depot build --platform linux/amd64 "$@" \
        -f "$dockerfile" -t "$image" --push "$context"
      ;;
    docker)
      require_tool docker
      docker buildx build --platform linux/amd64 "$@" \
        -f "$dockerfile" -t "$image" --push "$context"
      ;;
    *)
      err "Unsupported BUILDER=${BUILDER}; use depot or docker."
      ;;
  esac
}

if [[ "$BUILD_INDEXER" == "1" ]]; then
  docker_login "$INDEXER_IMAGE_REPOSITORY"
  # One Dockerfile, five targets: the control plane plus the worker images
  # referenced by the Pipeline resources in indexer/pipelines/ (extract, embed)
  # and the scheduled Function workers in indexer/udfs/ (trending, warm-blobs).
  build_image indexer/Dockerfile . "${INDEXER_IMAGE_REPOSITORY}:${IMAGE_TAG}" \
    --target api \
    --build-context "layer_client=${LAYER_CLIENT_CONTEXT}"
  build_image indexer/Dockerfile . "${INDEXER_IMAGE_REPOSITORY}:${IMAGE_TAG}-extract" \
    --target extract-chunk \
    --build-context "layer_client=${LAYER_CLIENT_CONTEXT}"
  build_image indexer/Dockerfile . "${INDEXER_IMAGE_REPOSITORY}:${IMAGE_TAG}-embed" \
    --target embed \
    --build-context "layer_client=${LAYER_CLIENT_CONTEXT}"
  # Scheduled Function workers (indexer/udfs/). deploy.sh applies pipelines/ but
  # not udfs/, so after deploy apply them manually: kubectl apply -f indexer/udfs/
  build_image indexer/Dockerfile . "${INDEXER_IMAGE_REPOSITORY}:${IMAGE_TAG}-trending" \
    --target trending \
    --build-context "layer_client=${LAYER_CLIENT_CONTEXT}"
  build_image indexer/Dockerfile . "${INDEXER_IMAGE_REPOSITORY}:${IMAGE_TAG}-warm-blobs" \
    --target warm-blobs \
    --build-context "layer_client=${LAYER_CLIENT_CONTEXT}"
fi

if [[ "$BUILD_SEARCH" == "1" ]]; then
  docker_login "$SEARCH_IMAGE_REPOSITORY"
  build_image search/Dockerfile . "${SEARCH_IMAGE_REPOSITORY}:${IMAGE_TAG}" \
    --build-context "layer_client=${LAYER_CLIENT_CONTEXT}"
fi

if [[ "$BUILD_WEB" == "1" ]]; then
  docker_login "$WEB_IMAGE_REPOSITORY"
  # The web image bundles the hev layer TypeScript client, vendored in-tree at
  # app/vendor/hevlayer (see app/Dockerfile; refresh with sync-ts-client.sh).
  build_image app/Dockerfile app "${WEB_IMAGE_REPOSITORY}:${IMAGE_TAG}"
fi

if [[ -n "$HEV_SHOP_EFS_FILE_SYSTEM_ID" ]]; then
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
fi

helm_args=(
  upgrade --install "$RELEASE" ./helm/hev-shop
  --namespace "$NAMESPACE"
  --create-namespace
)

if [[ -n "$INDEXER_IMAGE_REPOSITORY" ]]; then
  helm_args+=(--set "indexerImage.repository=${INDEXER_IMAGE_REPOSITORY}")
  helm_args+=(--set "indexerImage.tag=${IMAGE_TAG}")
fi
if [[ -n "$SEARCH_IMAGE_REPOSITORY" ]]; then
  helm_args+=(--set "searchImage.repository=${SEARCH_IMAGE_REPOSITORY}")
  helm_args+=(--set "searchImage.tag=${IMAGE_TAG}")
fi
if [[ -n "$WEB_IMAGE_REPOSITORY" ]]; then
  helm_args+=(--set "webImage.repository=${WEB_IMAGE_REPOSITORY}")
  helm_args+=(--set "webImage.tag=${IMAGE_TAG}")
fi
if [[ -n "$HELM_SET" ]]; then
  helm_args+=(--set "$HELM_SET")
fi
if [[ -n "$HELM_VALUES" ]]; then
  IFS=',' read -r -a value_files <<< "$HELM_VALUES"
  for value_file in "${value_files[@]}"; do
    [[ -n "$value_file" ]] && helm_args+=(-f "$value_file")
  done
fi

log "Deploying ${RELEASE} with Helm..."
helm "${helm_args[@]}"

# Worker Deployments + scaling are owned by the Layer operator. The committed
# manifests pin the ECR indexer image at :latest*; swap in the repo/tag we just
# pushed (`:latest-extract` -> `:${IMAGE_TAG}-extract`, same for embed).
log "Applying Layer Pipeline resources from indexer/pipelines/..."
for manifest in indexer/pipelines/*.yaml; do
  if [[ -n "$INDEXER_IMAGE_REPOSITORY" ]]; then
    sed "s|186219257916.dkr.ecr.us-east-1.amazonaws.com/hev-shop-indexer:latest|${INDEXER_IMAGE_REPOSITORY}:${IMAGE_TAG}|" "$manifest" \
      | kubectl apply -n "$NAMESPACE" -f -
  else
    kubectl apply -n "$NAMESPACE" -f "$manifest"
  fi
done

log "Waiting for core rollout..."
kubectl rollout status deployment/"${RELEASE}-indexer-api" -n "$NAMESPACE" --timeout=180s
kubectl rollout status deployment/"${RELEASE}-search" -n "$NAMESPACE" --timeout=180s
kubectl rollout status deployment/"${RELEASE}-web" -n "$NAMESPACE" --timeout=180s

# Fail the deploy if the read API can't authenticate to the Layer gateway. This
# catches an empty/invalid LAYER_GATEWAY_API_KEY at deploy time instead of via a
# user-facing 502 (the 2026-06-24 outage: a deploy blanked the key and every
# /search returned "search upstream 502"). A bad key makes /search return 502.
log "Verifying read API <-> Layer gateway auth..."
if kubectl exec -n "$NAMESPACE" "deploy/${RELEASE}-search" -- \
    python -c "import httpx,sys; r=httpx.post('http://localhost:8080/search', json={'query':'deploy auth check','top_k':1}, timeout=30); sys.exit(0 if r.status_code == 200 else 1)" >/dev/null 2>&1; then
  log "Read API <-> gateway auth OK."
else
  err "Read API got a non-200 from the Layer gateway (commonly an empty LAYER_GATEWAY_API_KEY). Check secrets.gatewayKeySecret / the '${NAMESPACE}/layer' secret before serving traffic."
fi

log "hev-shop deployed with Helm. Useful checks:"
log "  kubectl get pods -n ${NAMESPACE}"
log "  kubectl port-forward -n ${NAMESPACE} svc/${RELEASE}-search 18080:8080"
log "  kubectl port-forward -n ${NAMESPACE} svc/${RELEASE}-indexer-api 18081:8080"
