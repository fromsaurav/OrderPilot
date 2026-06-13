#!/usr/bin/env bash
# Retrieve the cluster kubeconfig after `terraform apply`.
# Copies /etc/rancher/k3s/k3s.yaml off the server node and rewrites the API endpoint from
# 127.0.0.1 to the server's public IP (the cert already has it as a TLS SAN), so kubectl works
# from your laptop. Writes ./kubeconfig at the repo root (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TFDIR="$ROOT/terraform"
OUT="$ROOT/kubeconfig"

IP="$(terraform -chdir="$TFDIR" output -raw server_public_ip)"
KEY="$(terraform -chdir="$TFDIR" output -raw ssh_key_path)"
# The output path is relative to the terraform/ dir; make it absolute so ssh finds it
# regardless of where this script is invoked from.
case "$KEY" in /*) ;; *) KEY="$TFDIR/${KEY#./}" ;; esac
SSH_OPTS=(-i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10)

echo "Waiting for SSH + k3s server readiness on $IP ..."
for i in $(seq 1 60); do
  if ssh "${SSH_OPTS[@]}" "ubuntu@$IP" 'test -f /tmp/k3s-server-ready' 2>/dev/null; then
    echo "  server ready"; break
  fi
  sleep 5
  [ "$i" = "60" ] && { echo "server did not become ready in time"; exit 1; }
done

ssh "${SSH_OPTS[@]}" "ubuntu@$IP" 'sudo cat /etc/rancher/k3s/k3s.yaml' \
  | sed "s/127.0.0.1/$IP/" > "$OUT"
chmod 600 "$OUT"

echo "kubeconfig written to $OUT"
echo "Use it with:  export KUBECONFIG=$OUT"
kubectl --kubeconfig "$OUT" get nodes -o wide 2>/dev/null || echo "(nodes not ready yet — re-run 'kubectl get nodes' shortly)"
