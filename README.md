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
| `docs/` | `DESIGN.md`, `ARCHITECTURE.md`, `DEMO.md` |

## Status

Phase 1 (local app) in progress. Cloud deploy instructions land with Phase 2–4.

## Quick start (local)

```bash
# From repo root — brings up Temporal dev server + Postgres + backend + worker
cd backend && docker compose up --build
# UI (separate terminal)
cd frontend && npm install && npm run dev
# Smoke test the full rules-only demo
./scripts/local_demo.sh
```

The system runs **fully with no LLM key present** (deterministic rules engine). The optional
Gemini call site is an enhancement with a hard fallback — see `docs/DESIGN.md`.

## Cloud deploy (AWS)

Prerequisites and the exact clean-account → working-system commands are documented in the
**Prerequisites** section below and in `scripts/standup.sh` (added in Phase 2).

<!-- TODO(phase2): AWS prerequisites + standup/teardown walkthrough -->
