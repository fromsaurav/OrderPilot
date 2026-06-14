#!/usr/bin/env bash
# Open the two port-forward tunnels (Temporal Web UI + Grafana) with auto-restart, so a silently
# dropped tunnel doesn't ruin a recording take. Ctrl+C stops both.
#
#   ./scripts/tunnels.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export KUBECONFIG="$ROOT/kubeconfig"

forward() {  # label namespace svc local:remote
  while true; do
    kubectl -n "$2" port-forward "svc/$3" "$4" >/dev/null 2>&1
    echo "[$1] tunnel dropped — restarting in 2s"
    sleep 2
  done
}

forward "temporal-ui" orderpilot temporal-ui 8080:8080 &
forward "grafana"     monitoring kps-grafana  3001:80 &

GRAFANA_PW="$(kubectl -n monitoring get secret kps-grafana -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d)"
cat <<EOF

Tunnels up (auto-restarting):
  Temporal Web UI -> http://localhost:8080
  Grafana         -> http://localhost:3001   (login: admin / ${GRAFANA_PW:-<see secret>})
                     dashboard: "OrderPilot — Cluster & Temporal"

Leave this running during the demo. Ctrl+C stops both tunnels.
EOF

trap 'kill 0' INT TERM
wait
