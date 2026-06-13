output "server_public_ip" {
  description = "Public IP of the k3s server node (kube API, SSH, API NodePort target)."
  value       = aws_instance.server.public_ip
}

output "agent_public_ip" {
  description = "Public IP of the k3s agent node."
  value       = aws_instance.agent.public_ip
}

output "server_private_ip" {
  description = "Private IP of the server (used by the agent to join)."
  value       = aws_instance.server.private_ip
}

output "ssh_key_path" {
  description = "Local path to the generated SSH private key (gitignored)."
  value       = local_sensitive_file.private_key.filename
}

output "ssh_server" {
  description = "Ready-to-run SSH command for the server node."
  value       = "ssh -i ${local_sensitive_file.private_key.filename} ubuntu@${aws_instance.server.public_ip}"
}

output "api_nodeport_url" {
  description = "Backend API base URL (set NEXT_PUBLIC_API_BASE to this for the local UI)."
  value       = "http://${aws_instance.server.public_ip}:${var.node_port}"
}

output "ecr_backend_repo_url" {
  value       = aws_ecr_repository.app["backend"].repository_url
  description = "ECR repo URL for the backend image."
}

output "ecr_worker_repo_url" {
  value       = aws_ecr_repository.app["worker"].repository_url
  description = "ECR repo URL for the worker image."
}

output "operator_cidr" {
  description = "CIDR currently allowed for SSH/kube-API/NodePort ingress."
  value       = local.operator_cidr
}

output "fetch_kubeconfig_hint" {
  description = "How to retrieve the kubeconfig after apply."
  value       = "./scripts/fetch_kubeconfig.sh   # scp k3s.yaml from the server and rewrite the API endpoint to the public IP"
}
