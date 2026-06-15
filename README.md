# OrderPilot — Order Supervisor on Self-Hosted Temporal

A long-running AI supervisor that oversees one e-commerce order from creation to completion,
built on **Temporal workflows**, with Temporal and a self-hosted **PostgreSQL** running on a
**two-node k3s cluster in AWS**, provisioned **100% with Terraform**.

> SagePilot Platform Engineer Task. Spec: the assignment PDF in the repo root.

**Status: complete and running end-to-end** — app (Part 1) + self-hosted infra (Part 2): k3s on
AWS via Terraform, self-hosted Temporal (SQL visibility, no Elasticsearch) + Postgres, FastAPI
backend, worker, trimmed Prometheus/Grafana monitoring, worker HPA scaling 1→4→1 under load.
Cloud end-to-end demo passes 17/17.

---

## Prerequisites

- An **AWS account** (credits recommended) and **AWS CLI v2** configured for it — an IAM user with
  `AdministratorAccess`, region `ap-south-1`.
- Local tools: **terraform ≥ 1.7, kubectl, helm, docker, jq, node/npm**. Verify with
  `./scripts/check_prereqs.sh`.
- *(Optional)* a **Gemini API key** (Google AI Studio) to enable the single LLM call site. The
  system runs fully without it.

## From a clean AWS account to a working system

```bash
# 0. one-time: point the AWS CLI at your account (credentials are never committed)
aws configure                 # access key + secret, region = ap-south-1
aws sts get-caller-identity   # confirms the IAM user

# 1. STAND IT ALL UP — one command.
#    terraform apply (VPC, 2x t3.medium k3s nodes, ECR) -> wait for k3s ->
#    build & push images to ECR -> deploy Postgres, Temporal, backend, worker,
#    monitoring + worker HPA -> seed demo data -> print access commands.
./scripts/standup.sh
#    To also enable the LLM path:   GEMINI_API_KEY=AIza... ./scripts/standup.sh
#    ~8-12 min; finishes with "OrderPilot is UP." and the commands for steps 2-3.

# 2. open the UI (runs locally, pointed at the cloud API NodePort)
API=$(terraform -chdir=terraform output -raw api_nodeport_url)
cd frontend && npm install && NEXT_PUBLIC_API_BASE="$API" npm run dev    # http://localhost:3000
cd ..

# 3. dashboards — never internet-exposed, reached via auto-restarting tunnels
./scripts/tunnels.sh          # Temporal UI http://localhost:8080 · Grafana http://localhost:3001

# 4. verify the whole flow end-to-end (17 assertions against the cloud API)
API="$API" ./scripts/local_demo.sh

# 5. autoscaling demo (two terminals)
KUBECONFIG=./kubeconfig kubectl -n orderpilot get hpa -w     # watch it scale
./scripts/load_test.sh                                       # drives worker CPU; replicas 1->4->1

# 6. TEAR IT ALL DOWN to ~$0 (terraform destroy + billable-orphan audit)
./scripts/teardown.sh
```

Full per-step breakdown, the **dynamic-IP "connection refused" fix**, resume steps, and a local
(no-AWS) path are in **[QUICKSTART.md](QUICKSTART.md)**.

---

## Design note — key decisions & why

- **k3s on EC2, not EKS.** k3s is a real, self-hosted Kubernetes with ~$0 control-plane cost and
  a <20-min create/destroy cycle, so the environment can be torn down nightly to stay near $0;
  EKS adds ~$0.10/hr and slower cycles for no benefit on a POC. **Two t3.medium** (server + agent)
  so the on-camera HPA load test has headroom — a single node left only ~300 MiB spare at peak.
- **Self-hosted PostgreSQL as an in-cluster StatefulSet on a k3s local-path volume.** It backs
  both Temporal (standard **SQL visibility, no Elasticsearch**) and the app's activity log. Using
  local-path rather than an EBS-CSI volume means nothing is orphaned by `terraform destroy`; the
  data is intentionally re-seedable (`scripts/seed_demo.sh`). RDS/Aurora are disallowed for the
  Temporal store and would also leave billable resources behind.
- **Network exposure.** Temporal's frontend `:7233` is a **ClusterIP — never internet-reachable**.
  The API is a **NodePort (30080)** with the security group locked to the operator's IP only — no
  `Service type=LoadBalancer`, which would create an ELB that survives `destroy` and keeps
  billing. The **Temporal Web UI and Grafana are never public** — reached via `kubectl
  port-forward`. Node-to-node SG rules are self-referencing only.
- **Secrets in Kubernetes Secrets.** The DB password and the optional Gemini key are created at
  standup from environment variables — never hardcoded, never committed. SSM would add an IAM
  instance role + fetch logic for just two secrets.
- **Agent = deterministic rules engine + one guarded LLM call (hybrid).** The rules/policy engine
  is the complete decision core, so the system runs fully and deterministically with **no API
  key**. Exactly one LLM call (Gemini, classifying `customer_message_received` text) lives inside
  a Temporal activity behind a **hard fallback** to the rules classifier on any failure (missing
  key, rate limit, bad response) — keeping workflow code deterministic and the demo reliable.

Full rationale, the alternatives weighed, and the infra gotchas hit & fixed:
[docs/DESIGN.md](docs/DESIGN.md).

---

## Docs

| Doc | What it covers |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | Run it (deployed vs local) + teardown / verify-$0 / resume / troubleshooting |
| [docs/DESIGN.md](docs/DESIGN.md) | Every decision + rationale (+ gotchas hit & fixed) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, workflow lifecycle, data model, cluster topology |
| [docs/BUSINESS_LOGIC.md](docs/BUSINESS_LOGIC.md) | How the app works, function by function |
| [docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md) | Command-by-command runbook + video narration |
| [docs/DEMO.md](docs/DEMO.md) | 10–15 min video shot list (mapped to the spec) |
| [docs/TOOLS.md](docs/TOOLS.md) | Per-tool quick reference |
| [docs/TERRAFORM.md](docs/TERRAFORM.md) · [docs/AWS.md](docs/AWS.md) · [docs/MONITORING.md](docs/MONITORING.md) · [docs/AUTOSCALING.md](docs/AUTOSCALING.md) | Plain-words tool primers |

## Repository layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI backend + Temporal worker, workflow, activities, rules engine + LLM call site |
| `frontend/` | Minimal Next.js UI |
| `terraform/` | Dedicated VPC, subnets, IGW, SGs, 2× EC2 (k3s), ECR — all AWS resources |
| `k8s/` | In-cluster manifests + monitoring Helm values (Postgres, Temporal, backend, worker, HPA) |
| `scripts/` | `standup.sh`, `teardown.sh`, `deploy.sh`, `seed_demo.sh`, `load_test.sh`, `tunnels.sh`, `fetch_kubeconfig.sh`, `local_demo.sh`, `check_prereqs.sh` |
| `docs/` | design + operator documentation (table above) |
