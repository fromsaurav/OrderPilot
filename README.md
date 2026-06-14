# OrderPilot — Order Supervisor on Self-Hosted Temporal

A POC long-running AI supervisor that oversees a single order from creation to completion,
built on **Temporal workflows**, with its orchestration backbone (Temporal + self-hosted
PostgreSQL) deployed on **Kubernetes (k3s) in AWS** and provisioned 100% with **Terraform**.

> SagePilot Platform Engineer Task. See the assignment PDF in the repo root for the spec.

**▶ Just want to run it? See [QUICKSTART.md](QUICKSTART.md)** — steps for both when the backend is
already deployed and when it isn't.

## Repository layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI backend + Temporal worker, workflow, activities, rules engine |
| `frontend/` | Minimal Next.js UI |
| `terraform/` | VPC, subnets, IGW, SGs, EC2 (k3s), ECR — all AWS resources |
| `k8s/` | In-cluster manifests/Helm values (Temporal, Postgres, backend, worker, monitoring) |
| `scripts/` | `standup.sh`, `teardown.sh`, `local_demo.sh`, `seed_demo.sh`, `load_test.sh` |
| `scripts/` | `standup.sh`, `teardown.sh`, `deploy.sh`, `local_demo.sh`, `seed_demo.sh`, `load_test.sh`, `tunnels.sh`, `fetch_kubeconfig.sh`, `check_prereqs.sh` |
| `docs/` | design + operator docs (see below) |

## Status

**Complete and running end-to-end.** Application (Part 1) + self-hosted infra (Part 2) both done:
two-node k3s on AWS via Terraform, self-hosted Temporal (SQL visibility, no Elasticsearch) +
Postgres, FastAPI backend, worker, trimmed Prometheus/Grafana monitoring, and a worker HPA
demonstrated scaling 1→4→1 under load. Cloud demo passes 17/17.

## Docs

| Doc | What it covers |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | Run it (deployed vs not) + teardown/verify-$0/resume runbook |
| [docs/BUSINESS_LOGIC.md](docs/BUSINESS_LOGIC.md) | How the app works, function by function |
| [docs/DESIGN.md](docs/DESIGN.md) | Every decision + rationale (+ gotchas hit & fixed) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, workflow lifecycle, data model, topology |
| [docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md) | Command-by-command runbook + video narration |
| [docs/DEMO.md](docs/DEMO.md) | 10–15 min video shot list (mapped to the spec) |
| [docs/TOOLS.md](docs/TOOLS.md) | Per-tool quick reference |
| [TERRAFORM](docs/TERRAFORM.md) · [AWS](docs/AWS.md) · [MONITORING](docs/MONITORING.md) · [AUTOSCALING](docs/AUTOSCALING.md) | Plain-words primers |

## Run it

See **[QUICKSTART.md](QUICKSTART.md)**. Shortest paths:

```bash
# Local only (no AWS): full stack on your laptop
cd backend && docker compose up -d --build
cd ../frontend && npm install && npm run dev          # http://localhost:3000
./scripts/local_demo.sh                               # 17-assertion smoke test

# Cloud (AWS): clean account -> demo-ready in one command
./scripts/standup.sh                                  # apply -> deploy -> monitor -> seed
./scripts/teardown.sh                                 # destroy + orphan audit ($0)
```

The agent runs **fully with no LLM key present** (deterministic rules engine); the optional Gemini
call site is an enhancement with a hard fallback — see [docs/DESIGN.md](docs/DESIGN.md) (Decision #3).
