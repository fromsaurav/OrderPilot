# Two t3.medium nodes (Decision #10). Server inits k3s; agent joins via the shared token.
# Root volumes are gp3 and delete on termination (no orphaned EBS after destroy).

locals {
  metadata = {
    http_endpoint = "enabled"
    http_tokens   = "optional" # allow simple IMDS curl in user-data for the node's public IP
  }
}

resource "aws_instance" "server" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.node.id]
  key_name                    = aws_key_pair.node.key_name
  associate_public_ip_address = true

  metadata_options {
    http_endpoint = local.metadata.http_endpoint
    http_tokens   = local.metadata.http_tokens
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/server-userdata.sh.tftpl", {
    k3s_token = random_password.k3s_token.result
    node_port = var.node_port
  })

  tags = { Name = "${local.name}-server", Role = "k3s-server" }
}

resource "aws_instance" "agent" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.node.id]
  key_name                    = aws_key_pair.node.key_name
  associate_public_ip_address = true
  depends_on                  = [aws_instance.server]

  metadata_options {
    http_endpoint = local.metadata.http_endpoint
    http_tokens   = local.metadata.http_tokens
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/agent-userdata.sh.tftpl", {
    k3s_token         = random_password.k3s_token.result
    server_private_ip = aws_instance.server.private_ip
  })

  tags = { Name = "${local.name}-agent", Role = "k3s-agent" }
}
