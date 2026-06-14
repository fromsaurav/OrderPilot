# Operator Guide — runbook & video narration cheat-sheet

> A beginner-friendly runbook for standing up, demoing, and tearing down the cloud environment.
> Expanded in Phase 5; this file already captures known gotchas as we hit them.

## Concepts in plain words

- **Local vs cluster:** in Phase 1 everything ran on my laptop via docker-compose. For grading,
  Temporal + Postgres + backend + worker run **on the AWS cluster**; only the Next.js frontend
  stays local, pointed at the cloud API (allowed by the assignment).
- **`kubectl port-forward`:** a temporary tunnel from a port on my laptop to a service inside the
  cluster. We use it because the Temporal Web UI and Grafana are deliberately **not** exposed to
  the internet. One command per UI, then it's a normal browser tab on `localhost`.
- **NodePort:** the one app port we expose on the server's public IP (`30080`), locked by the
  security group to **my IP only** — that's how the local UI reaches the cloud API.
- **Terraform state:** the file Terraform uses to remember what it built. It can contain secrets,
  so it's never committed; we keep it locally.

## Known issues & fixes

### Dynamic public IP → SSH / NodePort "connection refused"
The security group allows SSH (`22`), the kube API (`6443`), and the API NodePort (`30080`) **only
from my public IP** (`allowed_cidr`, auto-detected at apply time). If my ISP rotates my public IP
between sessions, the old `/32` rule no longer matches me and I'll see **connection refused /
timeouts** on SSH, `kubectl`, the port-forward tunnels, and the API.

**Symptom:** things that worked last session now hang or refuse, with no change on the cluster.

**Fix:** re-detect my IP and refresh the SG rule by re-applying — Terraform reads my current IP
and updates just the security-group ingress (no nodes recreated):
```bash
cd terraform
terraform apply -auto-approve      # re-detects current public IP via the http data source
```
To confirm what the SG currently allows:
```bash
terraform -chdir=terraform output operator_cidr
```
If I'm on a changing connection, I can also pin it explicitly to avoid surprises:
`terraform apply -var allowed_cidr=A.B.C.D/32`.

## Command-by-command runbook

> Stand up / tear down / resume live in [QUICKSTART.md](../QUICKSTART.md). This section is the
> "what each command means + what to say on camera" reference. Run from the repo root with
> `export KUBECONFIG=$PWD/kubeconfig` first.

### kubeconfig — `./scripts/fetch_kubeconfig.sh`
Copies the cluster credentials off the server and rewrites the API address to its public IP.
`standup.sh` runs it for you. **Say:** "This is the file kubectl uses to talk to the cloud cluster."

### `kubectl get nodes`
**Expect:** two rows, both `Ready` — one `control-plane` (server), one `<none>` (agent).
**Means:** the cluster is formed and the agent joined. `NotReady` for ~1 min after boot is normal;
if it persists see Troubleshooting. **Say:** "Two t3.medium nodes, both Ready — server and agent."

### `kubectl -n orderpilot get pods`
**Expect:** 5 pods `Running` 1/1: `postgres-0`, `temporal`, `temporal-ui`, `backend`, `worker`.
**Means:** the whole app is up. `Init:0/1` = waiting on its dependency (Postgres); `CrashLoopBackOff`
= read its logs. **Say:** "Temporal, Postgres, the API and the worker — all self-hosted on the cluster."

### Temporal Web UI — `kubectl port-forward -n orderpilot svc/temporal-ui 8080:8080`
Opens a tunnel to the in-cluster UI (it's not internet-exposed). Open `http://localhost:8080`.
**Show:** the workflow list, then click one order → its event history (signals, timers, activities).
**Say:** "This is Temporal itself — every order is one workflow; here's its full execution history."

### Grafana — `kubectl port-forward -n monitoring svc/kps-grafana 3001:80`
Open `http://localhost:3001`. **Login:** `admin` / password from the secret:
```bash
kubectl -n monitoring get secret kps-grafana -o jsonpath='{.data.admin-password}' | base64 -d
```
Open dashboard **"OrderPilot — Cluster & Temporal"**. Panels: node CPU/mem (cluster health),
Temporal task-latency p95 + request rate (Temporal activity), worker replicas + CPU (the HPA).
**Say:** "Prometheus scrapes the nodes and the Temporal server; this one dashboard shows cluster
health and Temporal activity." *(Both tunnels at once: `./scripts/tunnels.sh`.)*

### HPA under load — `kubectl -n orderpilot get hpa -w`  +  `./scripts/load_test.sh`
The `-w` watch streams the HPA live. **Reading it:** `TARGETS 149%/50%` = current vs target CPU;
`REPLICAS 1→4` = it's adding workers. After load stops, CPU falls and `REPLICAS` drops back to 1
(~1–2 min). **Say:** "Worker CPU crosses the 50% target, the autoscaler adds pods up to 4, then
removes them when the load clears — scale-up and scale-down."

### Reading logs when something is red
```bash
kubectl -n orderpilot logs deploy/backend --tail=50      # or deploy/worker, deploy/temporal
kubectl -n orderpilot describe pod <pod>                 # Events section explains Pending/Init/CrashLoop
```
**Say:** "If a pod is unhealthy, its logs and the describe Events tell you why."
