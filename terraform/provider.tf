terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State is local by default, which is fine to get started solo - the
  # state file just needs to not be lost (and never committed to a public
  # repo, since it will contain resource details). For anything beyond
  # solo/experimental use, switch this to a remote backend, e.g.:
  #
  # backend "s3" {
  #   bucket = "your-terraform-state-bucket"
  #   key    = "sensible-debate/terraform.tfstate"
  #   region = "ap-south-1"
  # }
}

provider "aws" {
  region = var.aws_region
}
