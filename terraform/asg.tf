data "aws_ami" "al2023_arm64" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-kernel-*-arm64"]
  }
  filter {
    name   = "architecture"
    values = ["arm64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  ecr_registry = split("/", aws_ecr_repository.app.repository_url)[0]
  image_uri    = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"

  # Exclude subnets in ap-south-1b to prevent launching in the capacity-constrained AZ
  asg_subnet_ids = [
    for s in aws_subnet.public : s.id if s.availability_zone != "${var.aws_region}b"
  ]

  user_data = templatefile("${path.module}/templates/user_data.sh.tpl", {
    aws_region             = var.aws_region
    ecr_registry            = local.ecr_registry
    image_uri               = local.image_uri
    db_password_param_name  = aws_ssm_parameter.db_password.name
    db_username              = var.db_username
    db_endpoint              = aws_db_instance.main.address
    db_name                  = var.db_name
    redis_endpoint           = aws_elasticache_cluster.main.cache_nodes[0].address
    argument_seconds         = var.argument_seconds
    reflection_seconds       = var.reflection_seconds
    log_group_name           = aws_cloudwatch_log_group.app.name
  })
}

resource "aws_launch_template" "app" {
  name_prefix   = "${var.project_name}-"
  image_id      = data.aws_ami.al2023_arm64.id
  instance_type = var.instance_type
  key_name      = var.ssh_key_name != "" ? var.ssh_key_name : null

  block_device_mappings {
    device_name = data.aws_ami.al2023_arm64.root_device_name
    ebs {
      volume_size           = 30
      volume_type           = "gp3"
      delete_on_termination = true
    }
  }

  iam_instance_profile {
    arn = aws_iam_instance_profile.app_instance.arn
  }

  network_interfaces {
    associate_public_ip_address = true
    security_groups              = [aws_security_group.app.id]
  }

  metadata_options {
    http_tokens   = "required" # IMDSv2 only
    http_endpoint = "enabled"
  }

  user_data = base64encode(local.user_data)

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.project_name}-app" }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "app" {
  name                = "${var.project_name}-asg"
  vpc_zone_identifier = local.asg_subnet_ids
  target_group_arns   = [aws_lb_target_group.app.arn]

  min_size         = var.asg_min_size
  max_size         = var.asg_max_size
  desired_capacity = var.asg_desired_capacity

  # ELB health (i.e. /healthz through the target group) decides whether
  # an instance is healthy, not just whether the EC2 status check passes -
  # grace period gives a fresh instance time to boot Docker, pull the
  # image and start the app before that's held against it.
  health_check_type         = "ELB"
  health_check_grace_period = 180

  launch_template {
    id      = aws_launch_template.app.id
    version = "$Latest"
  }

  # Changing the launch template (e.g. a new image_tag) and re-applying
  # triggers a rolling replacement automatically - see DEPLOYMENT_AWS.md
  # for the exact deploy workflow this enables.
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 180
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.project_name}-app"
    propagate_at_launch = true
  }
}

resource "aws_autoscaling_policy" "cpu_target_tracking" {
  name                   = "${var.project_name}-cpu-target-tracking"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = var.asg_cpu_target
  }
}
