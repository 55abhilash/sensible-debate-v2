# A single small Redis node, no replica. This isn't a cache in the usual
# sense - it's the shared coordination layer that makes horizontal
# scaling actually correct (see app/realtime.py). Losing it loses only
# *live* debate state (in-progress turns/timers); topics and every
# message already sent are safely in Postgres regardless - see
# README.md's "Known limitations" for what that means in practice.
#
# NOTE: as with RDS in rds.tf, double-check engine_version and
# parameter_group_name are still current before applying - run
# `aws elasticache describe-cache-engine-versions --engine redis` if
# the apply fails on either.

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project_name}-redis"
  subnet_ids = aws_subnet.public[*].id
}

resource "aws_elasticache_cluster" "main" {
  cluster_id           = "${var.project_name}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  port                 = 6379
  parameter_group_name = "default.redis7"

  subnet_group_name = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  tags = { Name = "${var.project_name}-redis" }
}
