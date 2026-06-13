# ECR repositories for the backend API and the Temporal worker images.
# force_delete = true so `terraform destroy` removes the repo even if it still holds images
# (otherwise destroy fails and leaves a billable-ish orphan). The frontend is NOT deployed
# (runs locally per PDF p.3), so it has no repo.

locals {
  ecr_repos = ["backend", "worker"]
}

resource "aws_ecr_repository" "app" {
  for_each     = toset(local.ecr_repos)
  name         = "${local.name}/${each.value}"
  force_delete = true

  image_scanning_configuration {
    scan_on_push = false
  }

  tags = { Name = "${local.name}-${each.value}" }
}
