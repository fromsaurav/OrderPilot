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
Tear everything down (and audit for billable orphans) when done:

```bash
./scripts/teardown.sh
```
