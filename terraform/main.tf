# Data sources + locals shared across the config.

# Latest Ubuntu 22.04 LTS (Canonical) amd64 HVM image — k3s runs cleanly on it.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Auto-detect the operator's public IP when allowed_cidr is not set. Not a secret; used only to
# lock the security group ingress to the current machine.
data "http" "myip" {
  count = var.allowed_cidr == "" ? 1 : 0
  url   = "https://checkip.amazonaws.com"
}

# Pre-shared k3s join token (random; lives only in local state, never committed). Both the
# server (--token) and the agent (K3S_TOKEN) use it, so the agent can join without fetching
# anything from the server.
resource "random_password" "k3s_token" {
  length  = 48
  special = false
}

locals {
  operator_cidr = var.allowed_cidr != "" ? var.allowed_cidr : "${chomp(data.http.myip[0].response_body)}/32"
  name          = var.project
}
