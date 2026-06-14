# DEMO — 10–15 min video shot list

Record **while the infrastructure is live** (PDF p.4). Each shot maps to a graded requirement and
cross-references the narration cheat-sheet in [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md).

## Before you hit record (off-camera setup)

```bash
cd /home/saurav/Saurav/OrderPilot
./scripts/standup.sh                 # ~8-12 min; ends with "OrderPilot is UP." + seeds data
./scripts/tunnels.sh                 # leave running: Temporal UI :8080, Grafana :3001
# In a 3rd terminal, start the frontend:
API=$(terraform -chdir=terraform output -raw api_nodeport_url)
cd frontend && NEXT_PUBLIC_API_BASE="$API" npm run dev     # http://localhost:3000
```
Have 4 tabs ready: the UI (`:3000`), Temporal Web UI (`:8080`), Grafana (`:3001`), and the AWS
console (EC2, ap-south-1). Have two spare terminals for the HPA watch + load test.

---

## The shots (in order)

| # | Requirement (PDF p.4) | Show / do | Say (1–2 lines) |
|---|---|---|---|
| 1 | **Live AWS infra** | AWS console → EC2 (2 running t3.medium) + VPC/SG; then terminal `terraform -chdir=terraform state list` | "Everything is Terraform-managed: a dedicated VPC, two t3.medium k3s nodes, security groups, ECR — no console clicking." |
| 2 | **Self-hosted on K8s** | `KUBECONFIG=./kubeconfig kubectl get nodes` then `kubectl -n orderpilot get pods` | "Two-node k3s. Temporal, Postgres, backend, worker all run as pods we deployed — Temporal is self-hosted, not Temporal Cloud." |
| 3 | **Self-hosted Postgres + SQL visibility** | `kubectl -n orderpilot get pods` (postgres-0); mention no Elasticsearch | "One self-hosted Postgres backs Temporal (standard SQL visibility, no Elasticsearch) and the app." |
| 4 | **Start a run** | UI → Start a run (order id, wake 5s) | "One Temporal workflow per order. It starts and immediately acknowledges the order." |
| 5 | **Temporal Web UI** | `:8080` → open the new workflow → event history | "Here's that exact workflow in Temporal — its full event history: signals, timers, activities." |
| 6 | **Inject events + sleep/wake (event)** | UI → inject `payment_confirmed` (routine → stays asleep), then `shipment_delayed` (risk → wakes) | "Routine events keep it asleep to save resources; a risky event wakes the agent — escalate + customer update appear in the log." |
| 7 | **Sleep/wake (timer)** | toggle **show debug** in the log; point at the periodic timer wakes | "It also wakes on a timer to re-check the order — these debug lines are the heartbeat; real decisions stay in the default view." |
| 8 | **Actions in the activity log** | the log: `escalate_to_fulfillment_team`, `send_customer_update`, `add_internal_note` | "The three actions are recorded to Postgres and shown here — nothing is sent externally." |
| 9 | **Add instruction to a live run** | UI → add `do not message the customer`; inject `shipment_delayed` again | "Instructions added mid-flight change behavior: now it escalates but suppresses the customer message." |
| 10 | **Pause / resume** | UI → Pause, inject an event (buffered), Resume | "Pause/resume are Temporal signals; events buffer while paused and process on resume." |
| 11 | **Terminate** | UI → Terminate | "Terminate uses Temporal's terminate API — completion is system-owned, never the agent's choice." |
| 12 | **System-owned completion + final summary** | start a fresh run, inject `delivered`; show status `completed` + summary line | "A terminal event completes the run and writes a final summary to the activity log." |
| 13 | **Grafana dashboard** | `:3001` → "OrderPilot — Cluster & Temporal" | "Cluster health (node CPU/mem), Temporal task latency and request rate — all scraped by Prometheus." |
| 14 | **HPA scaling under load** | terminal A: `kubectl -n orderpilot get hpa -w`; terminal B: `./scripts/load_test.sh`; Grafana panels 5+6 | "Load spikes worker CPU past 50%; the HPA scales 1→4. When load stops, it scales back to 1 — both directions." |
| 15 | **Clean teardown** (optional on-camera) | `./scripts/teardown.sh` → zero-orphan audit | "One command destroys everything and audits for leftovers — clean, zero-cost." |

---

## Timing guide (~13 min)

- Infra + cluster (shots 1–3): ~2.5 min
- App walkthrough (4–12): ~6 min
- Monitoring + HPA (13–14): ~3.5 min — the HPA scale-up/down takes ~3 min real time, narrate the
  Grafana panels while it happens
- Wrap / teardown (15): ~1 min

## Tips

- Pre-seed is already done by standup, so lists aren't empty — but **create at least one run live**
  (shot 4) so viewers see the wake/decide/act happen in real time.
- Start the **HPA watch + load test first** if you want it scaling in the background while you talk
  through Grafana.
- If a tunnel drops mid-take ("connection refused"), `tunnels.sh` auto-restarts it — just wait a
  beat. Full narration lines per command are in [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md).
