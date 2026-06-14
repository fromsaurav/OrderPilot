# Quick Start

How to run OrderPilot in two situations: **(A)** the backend is already deployed, or **(B)** it
isn't yet. The UI always runs locally; only the backend location changes.

> The UI reads the env var **`NEXT_PUBLIC_API_BASE`** to decide which API to call (defaults to
> `http://localhost:8000`).

---

## A. Backend already deployed (cloud cluster is up)

You only need to start the frontend and point it at the cloud API.

```bash
# 1. Get the cloud API URL (NodePort on the server's public IP)
cd /home/saurav/Saurav/OrderPilot
API=$(terraform -chdir=terraform output -raw api_nodeport_url)   # e.g. http://65.2.4.186:30080
echo "$API"
curl -s "$API/healthz"            # -> {"status":"ok"}

# 2. Run the frontend against the cloud API
cd frontend
NEXT_PUBLIC_API_BASE="$API" npm run dev      # -> http://localhost:3000
```

Optional:

```bash
# Seed some runs so the UI isn't empty
./scripts/seed_demo.sh

# View the Temporal Web UI (not public — reached via a tunnel)
export KUBECONFIG=$PWD/kubeconfig
kubectl port-forward -n orderpilot svc/temporal-ui 8080:8080   # -> http://localhost:8080
```

If the API/UI hangs with **connection refused**, your public IP probably rotated (the security
group is locked to it). Refresh it: `cd terraform && terraform apply -auto-approve`.

---

## B. Backend not deployed yet

Pick one.

### Option 1 — Local only (no AWS, fastest)

```bash
# 1. Bring up the full stack (Temporal + Postgres + backend + worker)
cd backend && docker compose up -d --build
curl -s localhost:8000/healthz     # -> {"status":"ok"} once ready (~1-2 min first time)

# 2. Run the UI (defaults to localhost:8000, so no env var needed)
cd ../frontend && npm install && npm run dev    # -> http://localhost:3000

# 3. (optional) prove the whole flow, and view Temporal
./scripts/local_demo.sh            # 17 assertions
#   Temporal Web UI: http://localhost:8080
```

Stop it: `cd backend && docker compose down` (add `-v` to wipe data).

### Option 2 — Cloud (AWS, full deployment)

Requires AWS CLI configured + terraform/kubectl/helm/docker. Verify with
`./scripts/check_prereqs.sh`.

```bash
# One command: terraform apply -> wait for k3s -> build/push images -> deploy -> seed
./scripts/standup.sh
```

It prints the API URL and the exact `npm run dev` command at the end — then follow **Section A**.
Tear everything down (and audit for billable orphans) when done — see the runbook below.

---

# Operations runbook — teardown · verify $0 · resume · troubleshooting

**Single source of truth for stopping and resuming.** Run everything from the repo root
`/home/saurav/Saurav/OrderPilot` unless noted. Region is `ap-south-1`.

## 1. TEAR DOWN  (run when you stop working — drops to $0)

```bash
cd /home/saurav/Saurav/OrderPilot
./scripts/teardown.sh
```

**It worked if the audit at the end shows all zeros:**

```
  available EBS volumes : 0
  ALB/NLB               : 0
  classic ELBs          : 0
  Elastic IPs           : 0
  running instances     : 0
✅ Clean teardown — no billable resources remain.
```

If instead it prints `❌ POSSIBLE LEAK ...`, use the manual fallback.

**Manual fallback (only if the script fails):**

```bash
# 1. Destroy via terraform
terraform -chdir=terraform destroy -auto-approve

# 2. Check for leftovers — each command should print NOTHING (empty)
aws ec2 describe-instances --region ap-south-1 \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'Reservations[].Instances[].InstanceId' --output text
aws ec2 describe-volumes --region ap-south-1 \
  --filters Name=status,Values=available --query 'Volumes[].VolumeId' --output text
aws ec2 describe-addresses --region ap-south-1 \
  --query 'Addresses[].AllocationId' --output text

# 3. Delete anything the commands above printed (paste the real id)
aws ec2 terminate-instances --region ap-south-1 --instance-ids <INSTANCE_ID>
aws ec2 delete-volume       --region ap-south-1 --volume-id   <VOLUME_ID>
aws ec2 release-address     --region ap-south-1 --allocation-id <ALLOC_ID>
```

Clean result = all three `describe-...` commands print empty.

**Final eyeball:** AWS Console → region **Asia Pacific (Mumbai) / ap-south-1** → **EC2 → Instances**.
The two instances (`orderpilot-server`, `orderpilot-agent`) must be **Terminated** (they disappear
after ~1 h). Nothing should be in the **Running** state.

## 2. VERIFY $0  (confirm nothing is billing)

```bash
# Must print NOTHING. No running instances = no compute charges.
aws ec2 describe-instances --region ap-south-1 \
  --filters Name=instance-state-name,Values=running,pending \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType]' --output text
```

Credits / spend: AWS Console → **Billing and Cost Management → Credits**
(<https://console.aws.amazon.com/billing/home#/credits>) — your $100 + $20 credit balance.

## 3. COME BACK / RESUME  (run when you return)

```bash
cd /home/saurav/Saurav/OrderPilot
./scripts/standup.sh
```

- **What it does:** `terraform apply` (recreate the 2 nodes) → wait for k3s → build + push images
  to ECR → deploy all pods → install monitoring + HPA → seed demo data → print access info.
- **How long:** ~8–12 min.
- **Success signal:** a banner ending with **`OrderPilot is UP.`** followed by a pod list.
  (standup runs `seed_demo.sh` for you, so the UI won't be empty.)

```bash
# The server's public IP changes every standup — get the current API URL:
API=$(terraform -chdir=terraform output -raw api_nodeport_url); echo "$API"
```

```bash
# Frontend (local, pointed at the cloud API) — self-contained, gets the current IP itself
cd /home/saurav/Saurav/OrderPilot
API=$(terraform -chdir=terraform output -raw api_nodeport_url)
cd frontend && NEXT_PUBLIC_API_BASE="$API" npm run dev          # -> http://localhost:3000
```

```bash
# UIs (never public) — auto-restarting tunnels; leave this terminal running
cd /home/saurav/Saurav/OrderPilot
./scripts/tunnels.sh
#   Temporal Web UI -> http://localhost:8080
#   Grafana         -> http://localhost:3001   (admin / password is printed by the script)
```

```bash
# (Optional) re-seed demo data manually — standup already did this once
cd /home/saurav/Saurav/OrderPilot && ./scripts/seed_demo.sh
```

**Health check — all three should be green:**

```bash
cd /home/saurav/Saurav/OrderPilot
export KUBECONFIG=$PWD/kubeconfig
kubectl -n orderpilot get pods            # 5 pods, all Running
curl -s "$(terraform -chdir=terraform output -raw api_nodeport_url)/healthz"   # {"status":"ok"}
./scripts/local_demo.sh                   # ends with "17 passed, 0 failed"
```

## 4. TROUBLESHOOTING (top 3)

- **Agent node `NotReady`** (`KUBECONFIG=./kubeconfig kubectl get nodes` shows the `<none>`-role
  node NotReady) → recreate just the agent:
  ```bash
  terraform -chdir=terraform apply -auto-approve -replace=aws_instance.agent
  ```
- **Connection refused** on SSH / `kubectl` / the API / the UIs (your public IP rotated; the
  security group is locked to it) → refresh the SG rule with your current IP:
  ```bash
  terraform -chdir=terraform apply -auto-approve
  ```
- **A browser tab (Temporal UI / Grafana) suddenly shows "connection refused"** (the port-forward
  dropped) → re-run the tunnels (auto-restarts both):
  ```bash
  ./scripts/tunnels.sh
  ```
