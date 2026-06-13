variable "aws_region" {
  description = "AWS region (kept consistent everywhere, incl. ECR URLs)."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Name prefix + tag for all resources."
  type        = string
  default     = "orderpilot"
}

variable "instance_type" {
  description = "EC2 instance type for both k3s nodes (assignment specifies t3.medium)."
  type        = string
  default     = "t3.medium"
}

variable "root_volume_gb" {
  description = "gp3 root volume size per node (<=30 per zero-cost rules)."
  type        = number
  default     = 30
}

variable "vpc_cidr" {
  description = "CIDR for the dedicated VPC (not the default VPC)."
  type        = string
  default     = "10.42.0.0/16"
}

variable "subnet_cidr" {
  description = "Public subnet CIDR (both nodes live here; no NAT, no private subnets)."
  type        = string
  default     = "10.42.1.0/24"
}

variable "node_port" {
  description = "NodePort for the FastAPI backend (30000-32767), reachable only from operator IP."
  type        = number
  default     = 30080
}

variable "allowed_cidr" {
  description = <<-EOT
    CIDR allowed to reach SSH (22), the kube API (6443) and the API NodePort. Leave empty to
    auto-detect the operator's current public IP (/32). Not a secret. Override if behind a
    changing IP, e.g. "203.0.113.4/32".
  EOT
  type        = string
  default     = ""
}
