# Single-AZ, small instance, short backup retention - the cheapest real
# Postgres RDS gets. This is a shared database used by every app
# instance (replacing the original SQLite file, which can't work once
# there's more than one process) - see README.md for why this changed.
#
# NOTE: check that db_engine_version below is still a supported RDS
# Postgres version before applying - AWS periodically retires old minor
# versions. `aws rds describe-db-engine-versions --engine postgres
# --query "DBEngineVersions[].EngineVersion"` shows what's current.

variable "db_engine_version" {
  type    = string
  default = "18.6"
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db"
  subnet_ids = aws_subnet.public[*].id
  tags       = { Name = "${var.project_name}-db-subnet-group" }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = var.db_engine_version

  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage_gb
  storage_type      = "gp3"
  # max_allocated_storage intentionally left unset - storage autoscaling
  # stays off, which keeps the monthly cost predictable.

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 3
  skip_final_snapshot     = true # fine for an MVP; set to false once this holds data you can't lose
  deletion_protection     = false

  tags = { Name = "${var.project_name}-db" }
}
