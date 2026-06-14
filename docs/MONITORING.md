# Monitoring (Prometheus + Grafana) — in simple words

> Status: **deployed** (Helm release `kps`, namespace `monitoring`). One dashboard:
> "OrderPilot — Cluster & Temporal".

## What it is
- **Prometheus** = a database that **collects numbers over time** ("metrics"): CPU, memory,
  how many workflows are running, request latency. It pulls these from each component every few
  seconds.
- **Grafana** = the **dashboard** that draws those numbers as graphs you can read at a glance.
- **kube-prometheus-stack** = a single Helm package that installs Prometheus + Grafana +
  the little agents that expose Kubernetes/node metrics — so we don't wire it all by hand.

## What it watches in OrderPilot
One Grafana dashboard showing:
- **Cluster health** — node CPU/memory, pod status (are things alive and not starved?).
- **Temporal activity** — running vs completed workflows, task latency (is the supervisor
  actually doing work?).
- **Worker load** — CPU of the Temporal worker, which is what drives autoscaling
  (see [AUTOSCALING.md](AUTOSCALING.md)).

## How you open it (it is NOT public)
Grafana is deliberately **not exposed to the internet** (a graded security point). You reach it
through a temporary tunnel from your laptop (or just run `./scripts/tunnels.sh`):
```bash
kubectl port-forward -n monitoring svc/kps-grafana 3001:80
# then open http://localhost:3001  ->  dashboard "OrderPilot — Cluster & Temporal"
```
Login is `admin`; the password is stored in a Kubernetes secret, read with:
```bash
kubectl -n monitoring get secret kps-grafana -o jsonpath='{.data.admin-password}' | base64 -d
```
A dropped tunnel shows "connection refused" in the browser — just re-run the port-forward
(`tunnels.sh` does this automatically with auto-restart).

## What we trimmed (and why)
To fit comfortably in memory and match the assignment scope:
- **Alertmanager OFF** — the assignment explicitly says no alerting rules.
- Short metric retention, only the exporters we actually show, and **resource limits on every
  pod** so nothing balloons.

## Why it's here (the graded reason)
The assignment requires a monitoring stack scraping Temporal + node/pod metrics with **at least
one dashboard** showing cluster health and Temporal activity. This is that.
