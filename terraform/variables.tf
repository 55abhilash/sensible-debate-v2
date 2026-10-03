variable "aws_region" {
  description = "AWS region to deploy into. ap-south-1 (Mumbai) is the default as the lowest-latency region for an India-based audience; change freely."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Used to name and tag every resource."
  type        = string
  default     = "sensible-debate"
}

variable "domain_name" {
  description = "Your domain, e.g. \"sensibledebate.com\" (no scheme, no www). Leave blank to deploy over plain HTTP only - fine for a first test, but you'll want HTTPS before posting this anywhere public. See DEPLOYMENT_AWS.md for the two-step process this requires (ACM needs a DNS record added at your registrar)."
  type        = string
  default     = ""
}

variable "instance_type" {
  description = "EC2 instance type for the Auto Scaling Group. t4g.* is Graviton (ARM64) - cheaper than the x86 t3.* equivalents for this workload."
  type        = string
  default     = "t4g.micro"
}

variable "ssh_key_name" {
  description = "Optional EC2 Key Pair name for SSH access."
  type        = string
  default     = ""
}

variable "asg_min_size" {
  type    = number
  default = 1
}

variable "asg_max_size" {
  description = "Ceiling on how many instances autoscaling can launch, however much traffic spikes. This is your cost safety valve - raise it once you trust the numbers, not before."
  type        = number
  default     = 4
}

variable "asg_desired_capacity" {
  type    = number
  default = 1
}

variable "asg_cpu_target" {
  description = "Target average CPU percent the Auto Scaling Group tries to maintain by adding/removing instances."
  type        = number
  default     = 50
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 20
}

variable "db_name" {
  type    = string
  default = "sensible_debate"
}

variable "db_username" {
  type    = string
  default = "sensible_debate_app"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "image_tag" {
  description = "Which tag in ECR to run. Changing this and re-applying is how you roll out a new version - see DEPLOYMENT_AWS.md."
  type        = string
  default     = "latest"
}

variable "argument_seconds" {
  description = "How long each turn to write an argument lasts."
  type        = number
  default     = 300
}

variable "reflection_seconds" {
  description = "How long the mandatory reflection pause lasts."
  type        = number
  default     = 120
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.20.1.0/24", "10.20.2.0/24", "10.20.3.0/24"]
}
