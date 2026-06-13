# One security group for both k3s nodes.
#  - Operator-only ingress: SSH, kube API, API NodePort (each from the operator IP /32).
#  - Node-to-node (self-referencing): k3s API, kubelet, flannel VXLAN — never public.
#  - Temporal frontend :7233 is a ClusterIP on the pod network (encapsulated in flannel VXLAN),
#    so it needs NO security-group rule and is never internet-reachable (hard constraint).

resource "aws_security_group" "node" {
  name        = "${local.name}-node-sg"
  description = "k3s nodes: operator-only admin ingress + node-to-node cluster traffic"
  vpc_id      = aws_vpc.main.id

  # --- operator-only ingress ---
  ingress {
    description = "SSH (operator only)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.operator_cidr]
  }
  ingress {
    description = "Kubernetes API for kubectl/port-forward (operator only)"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [local.operator_cidr]
  }
  ingress {
    description = "FastAPI backend NodePort (operator only)"
    from_port   = var.node_port
    to_port     = var.node_port
    protocol    = "tcp"
    cidr_blocks = [local.operator_cidr]
  }

  # --- node-to-node (self), never public ---
  ingress {
    description = "k3s supervisor/API node-to-node"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    self        = true
  }
  ingress {
    description = "kubelet (metrics-server, node-to-node)"
    from_port   = 10250
    to_port     = 10250
    protocol    = "tcp"
    self        = true
  }
  ingress {
    description = "flannel VXLAN overlay (node-to-node)"
    from_port   = 8472
    to_port     = 8472
    protocol    = "udp"
    self        = true
  }

  egress {
    description = "all egress (pull images, install k3s, AWS APIs)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-node-sg" }
}
