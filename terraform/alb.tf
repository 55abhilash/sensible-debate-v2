# See DEPLOYMENT_AWS.md, "A word about WebSockets" - the debate itself
# runs over one long-lived WebSocket per person, which can sit
# completely silent for up to argument_seconds at a time (5 minutes by
# default) while someone is writing. idle_timeout below is what stops
# the load balancer from killing that connection partway through a
# turn - it's the ALB equivalent of nginx's proxy_read_timeout in the
# original single-server deployment guide.

resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  load_balancer_type = "application"
  internal           = false
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
  idle_timeout       = 3600

  tags = { Name = "${var.project_name}-alb" }
}

resource "aws_lb_target_group" "app" {
  name     = "${var.project_name}-tg"
  port     = 8000
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  # A target only needs to drain, not linger - state is shared via
  # Redis now, so a client that gets bumped to another instance mid-scale-in
  # picks up exactly where it left off (its own JS also auto-reconnects).
  deregistration_delay = 60

  health_check {
    path                = "/healthz"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
    matcher             = "200"
  }

  # No stickiness on purpose: any instance can correctly serve any
  # request or WebSocket now (that's the whole point of the Redis
  # refactor), so there's nothing for stickiness to protect and it would
  # only get in the way of even load distribution.

  tags = { Name = "${var.project_name}-tg" }
}

resource "aws_acm_certificate" "main" {
  count             = var.domain_name != "" ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${var.project_name}-cert" }
}

# HTTP listener: redirects to HTTPS once a certificate is configured,
# otherwise serves the app directly over plain HTTP.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = var.domain_name != "" ? [1] : []
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = var.domain_name == "" ? [1] : []
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.app.arn
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = var.domain_name != "" ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.main[0].arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
