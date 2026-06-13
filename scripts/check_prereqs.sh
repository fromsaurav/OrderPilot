#!/usr/bin/env bash
# Verifies the local toolchain needed for Phase 2 (infra). Run before standup.
#
#   ./scripts/check_prereqs.sh
#
# Checks presence (and minimum version where it matters) of: terraform, kubectl, helm, aws,
# docker, jq — and that AWS credentials resolve. Exits non-zero if anything required is missing.
set -uo pipefail

MISS=0
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
bad()  { printf "  \033[31m✗ %s\033[0m\n" "$*"; MISS=$((MISS+1)); }
have() { command -v "$1" >/dev/null 2>&1; }

# terraform >= 1.7
if have terraform; then
  v=$(terraform version -json 2>/dev/null | jq -r .terraform_version 2>/dev/null || terraform version | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
  maj=${v%%.*}; rest=${v#*.}; min=${rest%%.*}
  if [ "$maj" -gt 1 ] || { [ "$maj" -eq 1 ] && [ "$min" -ge 7 ]; }; then ok "terraform $v (>=1.7)"; else bad "terraform $v too old (need >=1.7)"; fi
else bad "terraform not installed"; fi

if have kubectl; then
  kv=$(kubectl version --client -o json 2>/dev/null | jq -r .clientVersion.gitVersion 2>/dev/null)
  ok "kubectl: ${kv:-installed}"
else bad "kubectl not installed"; fi

for t in helm aws docker jq; do
  if have "$t"; then ok "$t: $($t --version 2>/dev/null | head -1)"; else bad "$t not installed"; fi
done

# AWS credentials resolve (no secrets printed — only the caller ARN).
if have aws; then
  if arn=$(aws sts get-caller-identity --query Arn --output text 2>/dev/null); then ok "aws auth: $arn"; else bad "aws credentials not resolving (run: aws configure)"; fi
fi

echo
if [ "$MISS" -eq 0 ]; then echo "All prerequisites satisfied."; else echo "$MISS prerequisite(s) missing."; exit 1; fi
