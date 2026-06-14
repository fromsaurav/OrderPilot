#!/usr/bin/env bash
# Deploy the app onto the running k3s cluster: build+push images to ECR, create secrets, apply
# all manifests, wait for rollouts. Idempotent — safe to re-run. Assumes ./kubeconfig exists
# (run scripts/fetch_kubeconfig.sh after terraform apply).
#
#   ./scripts/deploy.sh
#   GEMINI_API_KEY=xxx ./scripts/deploy.sh    # optional: enable the live LLM path
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export KUBECONFIG="$ROOT/kubeconfig"
REGION="$(aws configure get region 2>/dev/null || echo ap-south-1)"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REG="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
NS=orderpilot

echo "==> [1/6] ECR login + build + push images ($REG)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REG"
docker build -t "$REG/orderpilot/backend:latest" "$ROOT/backend"
docker push "$REG/orderpilot/backend:latest"
# Worker uses the same image (different command); push to its repo too.
docker tag "$REG/orderpilot/backend:latest" "$REG/orderpilot/worker:latest"
docker push "$REG/orderpilot/worker:latest"

echo "==> [2/6] namespace"
kubectl apply -f "$ROOT/k8s/00-namespace.yaml"

echo "==> [3/6] app secret (Decision #5)"
if ! kubectl -n "$NS" get secret orderpilot-secrets >/dev/null 2>&1; then
  PGPW="$(openssl rand -hex 16)"
  kubectl -n "$NS" create secret generic orderpilot-secrets \
    --from-literal=postgres-password="$PGPW" \
    --from-literal=gemini-api-key="${GEMINI_API_KEY:-}"
  echo "    created orderpilot-secrets (random postgres password)"
else
  echo "    orderpilot-secrets exists; keeping current postgres password"
  # Allow turning the LLM on later without rotating the DB password.
  if [ -n "${GEMINI_API_KEY:-}" ]; then
    kubectl -n "$NS" patch secret orderpilot-secrets \
      -p "{\"data\":{\"gemini-api-key\":\"$(printf %s "$GEMINI_API_KEY" | base64 -w0)\"}}"
  fi
fi

echo "==> [4/6] ECR image-pull secret (token ~12h; refreshed each deploy)"
kubectl -n "$NS" create secret docker-registry regcred \
  --docker-server="$REG" --docker-username=AWS \
  --docker-password="$(aws ecr get-login-password --region "$REGION")" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> [5/6] apply manifests"
kubectl apply -f "$ROOT/k8s/05-config.yaml"
kubectl apply -f "$ROOT/k8s/10-postgres.yaml"
kubectl apply -f "$ROOT/k8s/20-temporal.yaml"
kubectl apply -f "$ROOT/k8s/30-temporal-ui.yaml"
sed "s|__ECR_REGISTRY__|$REG|g" "$ROOT/k8s/40-backend.yaml" | kubectl apply -f -
sed "s|__ECR_REGISTRY__|$REG|g" "$ROOT/k8s/50-worker.yaml"  | kubectl apply -f -

echo "==> [6/6] wait for rollouts"
kubectl -n "$NS" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NS" rollout status deploy/temporal     --timeout=300s
kubectl -n "$NS" rollout status deploy/temporal-ui  --timeout=120s
kubectl -n "$NS" rollout status deploy/backend      --timeout=300s
kubectl -n "$NS" rollout status deploy/worker       --timeout=300s

echo
kubectl -n "$NS" get pods -o wide
echo
echo "API NodePort: $(terraform -chdir="$ROOT/terraform" output -raw api_nodeport_url 2>/dev/null || echo 'http://<server-ip>:30080')"
