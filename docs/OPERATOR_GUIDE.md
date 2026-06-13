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

<!-- TODO(phase5): full command-by-command runbook (kubeconfig, get nodes/pods, port-forwards,
     Grafana login, HPA watch, reading logs) + per-command "what to say on video" lines. -->
