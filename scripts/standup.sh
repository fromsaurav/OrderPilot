#!/usr/bin/env bash
# One command: clean AWS account -> demo-ready. terraform apply -> wait for k3s -> deploy app
# -> seed demo data -> print how to reach everything. Pair with scripts/teardown.sh at end of
# session (zero-cost rhythm).
#
#   ./scripts/standup.sh
#   GEMINI_API_KEY=xxx ./scripts/standup.sh   # also enable the live LLM path
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TFDIR="$ROOT/terraform"

echo "==> [1/4] terraform apply (infra)"
terraform -chdir="$TFDIR" apply -auto-approve

echo "==> [2/4] fetch kubeconfig + wait for both nodes Ready"
"$ROOT/scripts/fetch_kubeconfig.sh"
export KUBECONFIG="$ROOT/kubeconfig"
for _ in $(seq 1 40); do
  ready="$(kubectl get nodes --no-headers 2>/dev/null | grep -c ' Ready ')" || ready=0
  [ "${ready:-0}" -ge 2 ] && break
  sleep 6
done
kubectl get nodes

echo "==> [3/4] deploy app to the cluster"
"$ROOT/scripts/deploy.sh"

echo "==> [4/4] seed demo data"
"$ROOT/scripts/seed_demo.sh" || echo "(seed skipped/failed — not fatal)"

SERVER="$(terraform -chdir="$TFDIR" output -raw server_public_ip)"
NODEPORT="$(terraform -chdir="$TFDIR" output -raw api_nodeport_url)"
cat <<EOF

============================================================
 OrderPilot is UP.

 API (NodePort, operator-IP only):
   $NODEPORT

 Frontend (run locally against the cloud API):
   cd frontend && NEXT_PUBLIC_API_BASE=$NODEPORT npm run dev
   -> http://localhost:3000

 Temporal Web UI (port-forward; never public):
   kubectl port-forward -n orderpilot svc/temporal-ui 8080:8080
   -> http://localhost:8080

 (Grafana arrives in Phase 4.)

 Tear down at end of session:  ./scripts/teardown.sh
============================================================
EOF
