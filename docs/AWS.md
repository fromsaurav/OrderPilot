# AWS — in simple words

## What it is
AWS (Amazon Web Services) is the cloud provider that rents us the servers and network our system
runs on. We use a small, deliberately cheap slice of it.

## The pieces we use (and what each is)
| Piece | Plain meaning | In OrderPilot |
|---|---|---|
| **VPC** | Your own private network in the cloud | `10.42.0.0/16`, dedicated (not AWS's default VPC) |
| **Subnet** | An address range inside the VPC | one public subnet for both servers |
| **Internet Gateway** | The door between the VPC and the internet | lets the nodes pull images / be reached on allowed ports |
| **Security Group** | A firewall — which ports are open, to whom | see "firewall" below |
| **EC2** | A rented virtual server | **2 × t3.medium** (2 CPU, 4 GB each) running k3s |
| **ECR** | A private Docker image registry | stores our `backend` + `worker` images |

## The firewall (security group), in one glance
- **From your laptop only** (your IP, auto-detected as a `/32`): SSH `22`, Kubernetes API `6443`,
  and the API `NodePort 30080`.
- **Between the two servers only** (not the internet): k3s `6443`, kubelet `10250`, network
  overlay `8472/udp`.
- **Temporal port `7233` has no rule at all** — it lives inside the cluster only and is never
  reachable from the internet (a graded security requirement).

## Cost & the zero-cost rules
- Two t3.medium in Mumbai (`ap-south-1`) ≈ **$0.09/hour total**, covered by the **$120 credit**.
- We **never** create the expensive/leaky things: **no NAT gateway, no Elastic IP, no Load
  Balancer, no extra EBS volumes**. These either cost money hourly or survive `destroy` and keep
  billing. Storage is the server's own 30 GB disk, deleted with the server.
- **Rhythm:** `standup.sh` at the start of a session, `teardown.sh` at the end. The teardown
  script also checks for leftover billable resources and fails loudly if it finds any.

## Account setup (already done, one-time)
Paid-plan account, root secured with MFA, an IAM user `terraform-admin` with admin access, AWS
CLI configured for `ap-south-1`. We never put AWS keys in the repo or paste them into chat.

> How all this is created as code: [TERRAFORM.md](TERRAFORM.md). Why these choices: [DESIGN.md](DESIGN.md).
