# The DB password is generated once by Terraform and never appears in
# your .tf files, state diffs you might share, or plain-text anywhere -
# it's stored as a SecureString in SSM Parameter Store (free, unlike
# Secrets Manager's per-secret monthly charge), and each EC2 instance
# fetches it at boot using the narrow read-only IAM permission granted in
# iam.tf. It IS present in terraform.tfstate, though - keep that file
# private (see the backend note in provider.tf).

resource "random_password" "db" {
  length  = 32
  special = false # keep it URL-safe, since it goes straight into a postgresql:// connection string
}

resource "aws_ssm_parameter" "db_password" {
  name  = "/${var.project_name}/db-password"
  type  = "SecureString"
  value = random_password.db.result

  tags = { Name = "${var.project_name}-db-password" }
}
