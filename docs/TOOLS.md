# TOOLS — what each tool did in this project

Quick reference: one short blurb per tool, what specific job it does **here**, and the exact
commands we run with it. Deeper primers: [TERRAFORM.md](TERRAFORM.md) · [AWS.md](AWS.md) ·
[MONITORING.md](MONITORING.md) · [AUTOSCALING.md](AUTOSCALING.md).

### Terraform
Infrastructure-as-code. **Here:** provisions everything in AWS (VPC, subnet, IGW, SG, 2× EC2 k3s
nodes via user-data, ECR, keypair) and tears it down cleanly.
```bash
terraform -chdir=terraform apply -auto-approve
terraform -chdir=terraform output -raw api_nodeport_url
terraform -chdir=terraform destroy -auto-approve
```

### k3s (Kubernetes)
A lightweight Kubernetes distribution. **Here:** the cluster the whole app runs on — installed by
EC2 user-data; server node + agent node form a 2-node cluster (pod CIDR `10.244/16`, service CIDR
`10.96/16`, off the VPC range). Ships coredns, local-path storage, and metrics-server.

### kubectl
The Kubernetes CLI. **Here:** deploy manifests, inspect pods, port-forward the UIs, watch the HPA.
```bash
export KUBECONFIG=$PWD/kubeconfig
kubectl get nodes
kubectl -n orderpilot get pods
kubectl -n orderpilot get hpa -w
kubectl -n orderpilot logs deploy/worker --tail=50
```

### Helm
The Kubernetes package manager. **Here:** installs the monitoring stack (one chart instead of
dozens of hand-written manifests). Temporal/Postgres/app are plain manifests, not Helm.
```bash
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f k8s/monitoring/values.yaml
```

### Prometheus
A time-series metrics database that scrapes targets. **Here:** scrapes node/pod metrics and the
**Temporal server** metrics endpoint (`:9090`, enabled via `PROMETHEUS_ENDPOINT`). Installed by the
kube-prometheus-stack chart; no commands run directly.

### Grafana
Dashboards over Prometheus data. **Here:** one dashboard, "OrderPilot — Cluster & Temporal"
(cluster health + Temporal latency/requests + worker scaling). Reached via port-forward only.
```bash
kubectl -n monitoring port-forward svc/kps-grafana 3001:80
kubectl -n monitoring get secret kps-grafana -o jsonpath='{.data.admin-password}' | base64 -d
```

### metrics-server + HPA
metrics-server reports live pod CPU/memory; the HorizontalPodAutoscaler uses it to scale a
Deployment. **Here:** metrics-server is bundled by k3s; the HPA scales the **worker** 1→4 on CPU.
```bash
kubectl -n orderpilot get hpa worker
./scripts/load_test.sh        # drives CPU up to trigger scale-up, then scale-down
```

### Docker + ECR
Docker builds the backend/worker image; ECR (Elastic Container Registry) stores it for the cluster
to pull. **Here:** `deploy.sh` builds once and pushes to both ECR repos; pods pull via an
image-pull secret.
```bash
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <acct>.dkr.ecr.ap-south-1.amazonaws.com
docker build -t <repo>/orderpilot/backend:latest backend/ && docker push <repo>/orderpilot/backend:latest
```
