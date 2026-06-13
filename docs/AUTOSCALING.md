# Autoscaling (metrics-server + HPA) — in simple words

> Status: design locked; deployed in Phase 4. Commands below are what we run once it's installed.

## What it is
- **metrics-server** = a tiny component that reports **how much CPU/memory each pod is using**
  right now. Kubernetes doesn't ship this by default; autoscaling needs it.
- **HPA (Horizontal Pod Autoscaler)** = a rule that says *"keep average CPU around X%; if it
  goes higher, add more copies of this pod; if it drops, remove copies."* "Horizontal" = more
  copies, not bigger machines.

## What scales in OrderPilot
The **Temporal worker** (the process that runs workflow/activity code). The HPA watches its CPU:

```
target: 50% CPU   minReplicas: 1   maxReplicas: 4
```
When work piles up the worker's CPU climbs → HPA adds worker pods (scale **up**). When the work
drains → CPU falls → HPA removes pods (scale **down**). The Temporal task queue spreads work
across however many workers exist, so more workers = more throughput.

## How we demonstrate it
`scripts/load_test.sh` starts many runs / injects bursts of events to spike worker CPU. You
watch the autoscaler react live:
```bash
kubectl get hpa -w            # live: TARGETS (current%/target%) and REPLICAS climbing then falling
kubectl get pods -w           # new worker pods appearing, then terminating
```
Reading `kubectl get hpa`:
- `TARGETS 230%/50%` → CPU is way over target → it will scale up.
- `REPLICAS 1 → 4` → it added workers.
- After the load stops, CPU falls and `REPLICAS` drops back toward 1 (scale-down has a few
  minutes of cooldown so it doesn't flap).

## Why capped at 4
Two t3.medium have limited CPU/RAM. `maxReplicas: 4` with small per-worker resource requests
keeps the demo from exhausting the nodes — we show real scale up **and** down without anything
crashing on camera.

## Why it's here (the graded reason)
The assignment requires an HPA on the Temporal worker plus a load script that demonstrably
triggers **both** scale-up and scale-down. This is that.
