#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

MESH_REPO="${MESH_REPO:-../mesh}"
TF_DIR="${TF_DIR:-${MESH_REPO}/infra/terraform}"
AWS_REGION="${AWS_REGION:-us-east-1}"
SKIP_TERRAFORM="${SKIP_TERRAFORM:-0}"
INSTALL_NVIDIA_PLUGIN="${INSTALL_NVIDIA_PLUGIN:-1}"

for arg in "$@"; do
  case "$arg" in
    --skip-terraform) SKIP_TERRAFORM=1 ;;
    --skip-nvidia-plugin) INSTALL_NVIDIA_PLUGIN=0 ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

log() { echo "==> $*"; }
err() { echo "ERROR: $*" >&2; exit 1; }

if [[ "$SKIP_TERRAFORM" == "1" ]]; then
  log "Skipping terraform."
else
  log "Applying Terraform for Karpenter IAM and discovery tags..."
  terraform -chdir="$TF_DIR" init -input=false
  terraform -chdir="$TF_DIR" apply -auto-approve -input=false
fi

log "Reading Terraform outputs..."
CLUSTER_NAME=$(terraform -chdir="$TF_DIR" output -raw cluster_name 2>/dev/null || err "Missing terraform output: cluster_name")
CLUSTER_ENDPOINT=$(terraform -chdir="$TF_DIR" output -raw cluster_endpoint 2>/dev/null || err "Missing terraform output: cluster_endpoint")
KARPENTER_ROLE_ARN=$(terraform -chdir="$TF_DIR" output -raw karpenter_controller_role_arn 2>/dev/null || err "Missing terraform output: karpenter_controller_role_arn")
NODE_INSTANCE_PROFILE=$(terraform -chdir="$TF_DIR" output -raw karpenter_node_instance_profile_name 2>/dev/null || err "Missing terraform output: karpenter_node_instance_profile_name")
KARPENTER_VERSION=$(terraform -chdir="$TF_DIR" output -raw karpenter_chart_version 2>/dev/null || echo "1.12.1")
K8S_VERSION=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" --query 'cluster.version' --output text)

log "Updating kubeconfig..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"

log "Installing/upgrading Karpenter ${KARPENTER_VERSION}..."
helm registry logout public.ecr.aws >/dev/null 2>&1 || true
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version "$KARPENTER_VERSION" \
  --namespace kube-system \
  --create-namespace \
  --set "settings.clusterName=${CLUSTER_NAME}" \
  --set "settings.clusterEndpoint=${CLUSTER_ENDPOINT}" \
  --set "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn=${KARPENTER_ROLE_ARN}" \
  --set replicas=1 \
  --set nodeSelector.mesh-role=infra \
  --set tolerations[0].key=mesh-role \
  --set tolerations[0].operator=Equal \
  --set tolerations[0].value=infra \
  --set tolerations[0].effect=NoSchedule \
  --wait

if [[ "$INSTALL_NVIDIA_PLUGIN" == "1" ]]; then
  log "Installing/upgrading NVIDIA device plugin for Karpenter GPU nodes..."
  helm repo add nvdp https://nvidia.github.io/k8s-device-plugin >/dev/null 2>&1 || true
  helm repo update nvdp
  helm upgrade --install nvidia-device-plugin nvdp/nvidia-device-plugin \
    --namespace nvidia-device-plugin \
    --create-namespace \
    --set nodeSelector.mesh-role=gpu \
    --set tolerations[0].key=nvidia.com/gpu \
    --set tolerations[0].operator=Exists \
    --set tolerations[0].effect=NoSchedule \
    --wait
fi

log "Applying hev-shop CPU and GPU NodePools..."
kubectl apply -f - <<EOF
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: hev-shop-cpu
spec:
  amiFamily: AL2023
  instanceProfile: ${NODE_INSTANCE_PROFILE}
  amiSelectorTerms:
    - ssmParameter: /aws/service/eks/optimized-ami/${K8S_VERSION}/amazon-linux-2023/x86_64/standard/recommended/image_id
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: ${CLUSTER_NAME}
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: ${CLUSTER_NAME}
  tags:
    Project: hev-mesh
    Environment: bench
    ManagedBy: karpenter
    karpenter.sh/discovery: ${CLUSTER_NAME}
---
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: hev-shop-cpu
spec:
  template:
    metadata:
      labels:
        mesh-role: app
        workload: hev-shop
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: hev-shop-cpu
      expireAfter: 24h
      taints:
        - key: mesh-role
          value: app
          effect: NoSchedule
      requirements:
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
        - key: kubernetes.io/os
          operator: In
          values: ["linux"]
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["5"]
  limits:
    cpu: "32"
    memory: 128Gi
  disruption:
    consolidationPolicy: WhenEmpty
    consolidateAfter: 10m
---
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: hev-shop-gpu
spec:
  amiFamily: AL2023
  instanceProfile: ${NODE_INSTANCE_PROFILE}
  amiSelectorTerms:
    - ssmParameter: /aws/service/eks/optimized-ami/${K8S_VERSION}/amazon-linux-2023/x86_64/nvidia/recommended/image_id
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: ${CLUSTER_NAME}
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: ${CLUSTER_NAME}
  tags:
    Project: hev-mesh
    Environment: bench
    ManagedBy: karpenter
    karpenter.sh/discovery: ${CLUSTER_NAME}
---
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: hev-shop-gpu
spec:
  template:
    metadata:
      labels:
        mesh-role: gpu
        workload: hev-shop
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: hev-shop-gpu
      expireAfter: 24h
      taints:
        - key: nvidia.com/gpu
          value: "true"
          effect: NoSchedule
      requirements:
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
        - key: kubernetes.io/os
          operator: In
          values: ["linux"]
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot", "on-demand"]
        - key: node.kubernetes.io/instance-type
          operator: In
          values:
            - g4dn.xlarge
            - g4dn.2xlarge
            - g4dn.4xlarge
            - g5.xlarge
            - g5.2xlarge
            - g5.4xlarge
  limits:
    cpu: "32"
    memory: 128Gi
  disruption:
    consolidationPolicy: WhenEmpty
    consolidateAfter: 10m
EOF

log "Waiting for Karpenter resources to become ready..."
kubectl wait --for=condition=Ready ec2nodeclass/hev-shop-cpu --timeout=180s
kubectl wait --for=condition=Ready ec2nodeclass/hev-shop-gpu --timeout=180s
kubectl wait --for=condition=Ready nodepool/hev-shop-cpu --timeout=180s
kubectl wait --for=condition=Ready nodepool/hev-shop-gpu --timeout=180s

log "Karpenter is installed. Watch with:"
log "  kubectl get pods -n kube-system -l app.kubernetes.io/name=karpenter"
log "  kubectl get nodepools,ec2nodeclasses,nodeclaims"
