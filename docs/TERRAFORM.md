# Terraform — in simple words

## What it is
Terraform lets you describe cloud infrastructure as **text files** (`.tf`). You write *what you
want* (a VPC, two servers, etc.), and Terraform figures out the API calls to create, change, or
delete it. One command builds everything; one command tears it all down. No clicking in the AWS
console.

## What it does in OrderPilot
All AWS infrastructure lives in [`terraform/`](../terraform/) and is built by Terraform — nothing
is created by hand. It provisions **14 resources**:

- a dedicated **VPC** + public **subnet** + **internet gateway** + route table (our own private
  network, not AWS's default one),
- one **security group** (firewall rules — see [AWS.md](AWS.md)),
- **two t3.medium EC2 servers** (the k3s Kubernetes nodes),
- two **ECR** repositories (where our Docker images are stored),
- an **SSH key pair** + a random **k3s join token** so the two servers can form one cluster.

## The only commands you need
```bash
cd terraform
terraform init      # one-time: download the AWS plugin
terraform plan      # DRY RUN — shows what would change, creates nothing
terraform apply     # actually build it (asks yes/no)
terraform destroy   # delete everything we created
```
Reading `plan`/`apply` output — one line matters:
`Plan: 14 to add, 0 to change, 0 to destroy` → 14 new things, nothing modified or deleted.

## State — and why it's never in git
Terraform remembers what it built in a file called **`terraform.tfstate`**. It can contain
secrets (our SSH private key), so it is **gitignored and never committed**. We keep it locally
(fine for a short-lived POC).

## Why Terraform here (the graded reason)
The assignment requires the whole environment to come up from `terraform apply` on a clean
account and tear down cleanly with `terraform destroy`. Doing it as code makes that repeatable
and auditable — and lets us destroy nightly to spend ≈ $0.

> Design choices (two nodes, k3s via user-data, etc.) and *why*: see [DESIGN.md](DESIGN.md).
