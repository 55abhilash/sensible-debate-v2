output "alb_dns_name" {
  description = "Point your domain's CNAME (or A/ALIAS record) at this. If domain_name was left blank, this URL works directly over HTTP."
  value       = aws_lb.main.dns_name
}

output "ecr_repository_url" {
  description = "Where to `docker push` the app image - see DEPLOYMENT_AWS.md."
  value       = aws_ecr_repository.app.repository_url
}

output "db_endpoint" {
  description = "RDS Postgres endpoint (host:port). Not internet-reachable - only the app instances can connect to it."
  value       = aws_db_instance.main.address
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint. Not internet-reachable."
  value       = aws_elasticache_cluster.main.cache_nodes[0].address
}

output "asg_name" {
  description = "Pass this to `aws autoscaling start-instance-refresh --auto-scaling-group-name` to roll out a new image without changing any Terraform variables."
  value       = aws_autoscaling_group.app.name
}

output "acm_certificate_validation_records" {
  description = "If domain_name was set: add each of these as a DNS record at your domain registrar (Hostinger, GoDaddy, etc.) to prove you own the domain. Leave empty if domain_name was blank."
  value = var.domain_name != "" ? [
    for dvo in aws_acm_certificate.main[0].domain_validation_options : {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  ] : []
}

output "log_group_name" {
  description = "CloudWatch log group holding every instance's container output. `aws logs tail <this> --follow` is the fastest way to watch the whole fleet."
  value       = aws_cloudwatch_log_group.app.name
}

output "ssm_shell_access_hint" {
  description = "How to get a shell on a running instance without SSH/a bastion (once you have an instance id from the EC2 console or `aws autoscaling describe-auto-scaling-groups`)."
  value       = "aws ssm start-session --target <instance-id> --region ${var.aws_region}"
}
