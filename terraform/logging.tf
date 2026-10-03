# Container stdout/stderr from every instance flows here (via the
# awslogs docker log driver, configured in templates/user_data.sh.tpl),
# so you can watch what's happening across the whole fleet in one place
# instead of SSM-ing into individual boxes - particularly worth having
# during exactly the kind of traffic spike this is all built for.
# 14-day retention keeps the storage cost trivial.

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project_name}/app"
  retention_in_days = 14

  tags = { Name = "${var.project_name}-app-logs" }
}
