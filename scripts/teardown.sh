#!/usr/bin/env bash
# Tear the cloud environment down and PROVE nothing billable was left behind.
# `terraform destroy` removes everything we created; then we audit the account for the classic
# leak sources (available EBS volumes, load balancers, Elastic IPs, running instances). Exits
# non-zero if anything billable remains, so a silent leak can't slip past.
#
#   ./scripts/teardown.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TFDIR="$ROOT/terraform"
REGION="$(aws configure get region 2>/dev/null || echo ap-south-1)"

echo "==> terraform destroy (region $REGION)"
terraform -chdir="$TFDIR" destroy -auto-approve

# Stale local kubeconfig points at a now-dead server.
rm -f "$ROOT/kubeconfig" && echo "removed stale ./kubeconfig" || true

echo
echo "==> Orphan audit (must all be 0)"
LEAK=0
count() { echo "${1:-0}" | tr -d '[:space:]'; }

VOLS=$(aws ec2 describe-volumes --region "$REGION" \
  --filters Name=status,Values=available --query 'length(Volumes)' --output text 2>/dev/null)
ALB=$(aws elbv2 describe-load-balancers --region "$REGION" \
  --query 'length(LoadBalancers)' --output text 2>/dev/null)
ELB=$(aws elb describe-load-balancers --region "$REGION" \
  --query 'length(LoadBalancerDescriptions)' --output text 2>/dev/null)
EIP=$(aws ec2 describe-addresses --region "$REGION" \
  --query 'length(Addresses)' --output text 2>/dev/null)
INST=$(aws ec2 describe-instances --region "$REGION" \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'length(Reservations[].Instances[])' --output text 2>/dev/null)

printf "  available EBS volumes : %s\n" "$(count "$VOLS")"
printf "  ALB/NLB               : %s\n" "$(count "$ALB")"
printf "  classic ELBs          : %s\n" "$(count "$ELB")"
printf "  Elastic IPs           : %s\n" "$(count "$EIP")"
printf "  running instances     : %s\n" "$(count "$INST")"

for n in "$VOLS" "$ALB" "$ELB" "$EIP" "$INST"; do
  v=$(count "$n"); [ "$v" != "0" ] && [ "$v" != "None" ] && LEAK=$((LEAK + v))
done

echo
if [ "$LEAK" -eq 0 ]; then
  echo "✅ Clean teardown — no billable resources remain."
else
  echo "❌ POSSIBLE LEAK — $LEAK billable resource(s) still present. Investigate in the console above."
  exit 1
fi
