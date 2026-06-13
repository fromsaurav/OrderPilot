# DESIGN — Order Supervisor on Self-Hosted Temporal

Design note required by the assignment (PDF p.4): key decisions and **why**. Decisions are
owned by the project owner; this file is the running log. Each entry records the decision and
its rationale at the time it was made.

> Source of truth is the assignment PDF (`Platform Engineer Task — Order Supervisor on
> Self-Hosted Temporal.pdf`). Where this doc and the PDF disagree, the PDF wins.

---

## PDF verification notes (June 12)

Cross-checked the working brief against the PDF. No conflicts on any hard requirement. Two
notes recorded as conscious choices, not gaps:

- **Event set (PDF p.2):** the Event Generator lists 8 events including `payment_failed`:
  `order_created`, `payment_confirmed`, `payment_failed`, `shipment_created`,
  `shipment_delayed`, `delivered`, `refund_requested`, `customer_message_received`.
  `cancelled` appears only under "Run Completion" as a terminal order event, **not** in the
  generator list. Decision: treat `cancelled` as an injectable terminal event anyway, since
  completion logic references it. The UI/event generator exposes 9 injectables (8 + `cancelled`).
- **Agent decision step (PDF p.1):** spec allows a real LLM call *or* a deterministic rules
  engine — "your choice, document why." We use a **hybrid** (see Decision #3).

---

## Locked decisions

### Decision #1 — Kubernetes substrate: **k3s on EC2** (single node)
- **Rationale:** ~$0 control-plane cost vs EKS's ~$0.10/hr; full `apply`→`destroy` in <20 min,
  which makes the nightly zero-cost teardown rhythm cheap and the README clean-account claim
  testable repeatedly; leak-proof (no managed control plane / node groups left billing).
  Assignment explicitly recommends k3s single-node (PDF p.3).
- **Cost accepted:** k3s bootstrap via EC2 user-data adds some Terraform complexity (bootstrap
  method is Decision #7, to be locked at the Phase 2 gate).

### Decision #2 — PostgreSQL placement: **in-cluster StatefulSet + k3s local-path**
- **Rationale:** simplest and leak-proof. Uses k3s's built-in local-path provisioner — **no EBS
  CSI driver / no dynamically-provisioned EBS PVs**, which avoids orphaned-volume billing that
  survives `terraform destroy`. One Postgres serves both Temporal persistence and the app DB.
- **Cost accepted:** data is lost on teardown. Acceptable — the demo is re-seedable via
  `scripts/seed_demo.sh`. (PDF p.2 explicitly allows in-cluster StatefulSet.)

### Decision #3 — Agent decision step: **hybrid (rules core + one guarded LLM call site)** [pre-decided in brief]
- **Rationale:** determinism and demo reliability live in the rules engine; the LLM adds a
  single, isolated capability without putting non-determinism in the workflow.
- **Shape:** the rules/policy engine is the complete, self-sufficient decision core — the full
  demo passes with **no API key present**. Exactly one LLM call site: a **Gemini (free tier)**
  call inside a dedicated Temporal **activity** that classifies/summarizes
  `customer_message_received` text; its result feeds the rules engine.
- **Determinism boundary:** the LLM call lives in an **activity**, never in workflow code
  (workflow code must be deterministic for Temporal replay). The workflow only ever sees the
  classified result, or the fallback.
- **Fallback guard:** on *any* failure (missing key, rate limit, timeout, malformed response)
  fall back to the rules-only path and write an `add_internal_note`-style activity-log record
  noting the fallback. This keeps the demo deterministic.
- **Secrets:** Gemini key in a K8s Secret → env var → activity. Never in workflow code, never
  committed.

### Decision #8 — App DB schema management: **idempotent init SQL at backend startup**
- **Rationale:** backend runs `CREATE TABLE IF NOT EXISTS` (+ indexes) on boot; Temporal's own
  schema is applied by `temporal-sql-tool`. Zero migration framework, identical behavior local
  and in-cluster. Fits the "keep it minimal" scope boundary. (Alembic / init-Job rejected as
  overkill for a single activity-log table.)

### Decision #9 — Timers: **60s default scheduled wake, 24h default max run age, both per-run overridable**
- **Rationale:** a 60s wake interval produces several *visible* timer wakes during a 10–15 min
  demo recording. A 24h default max age means runs don't die mid-walkthrough, while a per-run
  override (e.g. 3 min) lets the demo show age-based system-owned completion on command.
- **Refinement (owner-added):** a timer wake writes a **visible** activity-log entry **only when
  the agent actually decides an action**. No-op wakes ("woke, nothing to do, sleeping") are
  recorded at a filtered/`debug` visibility level (or collapsed for consecutive no-ops) so the
  UI's default view shows only meaningful lines and the log isn't buried at 60s cadence for
  hours. Implemented via a `visibility` (or `level`) column on the activity-log table + a
  default UI filter. Temporal history itself is fine at this cadence for a 24h run — this is
  purely a log-readability concern.

---

## Phase 2 infra decisions (LOCKED — June 12 evening)

### Decision #4 — API exposure: **NodePort + EC2 public IP, SG locked to operator IP**
- **Rationale:** `type=LoadBalancer` is banned (creates an ELB outside Terraform state that
  survives `destroy` and keeps billing). Ingress means running an ingress controller for no
  benefit at one-API/one-cluster scale. NodePort (`30080`) reachable only from the operator's
  IP is the zero-cost requirement and the simplest thing to defend. The local Next.js UI points
  at `http://<server-public-ip>:30080`.

### Decision #5 — Secrets: **K8s Secrets**
- **Rationale:** only two secrets exist (Postgres password, optional Gemini key). Created at
  standup from local env vars (never committed). Zero extra plumbing. SSM would add an IAM
  instance role + fetch logic for no real gain on a POC.

### Decision #6 — Temporal install: **hand-written manifests using the `temporalio/auto-setup` image**
- **Rationale:** the same image our docker-compose already runs successfully against Postgres
  (SQL visibility, no Elasticsearch). Proven, lightest (one pod ~600 MiB vs the Helm chart's
  four service pods), and easiest to defend on video ("identical to what we tested locally").
  Re-runs idempotent schema setup on start, which also fits the re-seedable demo rhythm.

### Decision #7 — k3s bootstrap: **EC2 user-data (pure Terraform)**
- **Rationale:** no documented bootstrap exception needed, no SSH dependency during `apply`.
  Server node inits the cluster; agent node joins via a pre-generated shared token (random,
  in local state only) + the server's private IP. `remote-exec` is racy (couples apply to SSH);
  a manual step breaks the 100%-Terraform goal.

### Decision #10 — Node count: **TWO t3.medium (k3s server + agent)**
- **Rationale:** single-node RAM budget left only ~300 MiB headroom at the moment monitoring and
  the HPA load test run **together** — which is exactly the on-camera moment. The brief ranks
  demo reliability above minimalism, and the HPA load test *deliberately* spikes resource use,
  so we size for reliability. Two nodes put the scaling workers + headroom on node 2 and remove
  the OOM risk. Cost: multi-node k3s (agent join token + a few node-to-node SG rules) and ~2×
  compute, comfortably inside the $120 credit.
- **Topology:** one user-data template per role. Server inits k3s (`--node-external-ip`,
  `--tls-san` = its public IP via IMDS, traefik + servicelb disabled, NodePort only). Agent
  waits for `https://<server-private-ip>:6443/ping` then joins with `K3S_URL` + `K3S_TOKEN`.
- **Node-to-node SG (self-referencing, never public):** k3s API `6443/tcp`, kubelet `10250/tcp`,
  flannel VXLAN `8472/udp`. Operator-only ingress: SSH `22`, kube API `6443`, NodePort `30080`,
  each from the operator IP only. Temporal `7233` stays a ClusterIP (pod network) — no SG rule,
  never exposed.
- **Monitoring trim (applies regardless):** Alertmanager disabled (PDF: no alerting), only the
  exporters we show, explicit resource requests/limits on every pod, one Grafana dashboard.

---

## Status log

- **June 12 — Phase 0 + Phase 1 complete (local).** Full rules-only application working
  end-to-end on a docker-compose stack (self-hosted Temporal on self-hosted Postgres, SQL
  visibility, no Elasticsearch). All three inference triggers, pre-wake check, three actions +
  activity log, instruction overrides, all lifecycle controls, all three system-owned
  completion paths verified via `scripts/local_demo.sh` (17 assertions). Next.js UI builds and
  serves. Single Gemini call site present with a hard fallback proven by `test_llm_fallback.py`
  (runs deterministically with no/broken key). 19 rules + 4 fallback unit tests pass.
- **Next:** Phase 2 gate (June 13) — lock deferred infra decisions (#4–7, #10) then build
  Terraform (VPC/subnets/IGW/SGs/EC2/ECR), k3s bootstrap, deploy, monitoring, HPA.

## Standing constraints (from brief §8 — never violate)
- No Elasticsearch. No RDS/Aurora/Supabase. No Temporal Cloud. No NAT gateway. No default VPC.
- Port 7233 never open to `0.0.0.0/0`. Temporal Web UI never unauthenticated-public.
- No credentials or tfstate in git (`.gitignore` from commit 1; local TF state).
- Every AWS resource in Terraform except documented bootstrap exceptions.
- Demo reliability > features.
