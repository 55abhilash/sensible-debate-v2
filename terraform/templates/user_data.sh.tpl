#!/bin/bash
# Runs once when an instance boots (both the first instances and every
# one autoscaling launches later). Installs Docker, authenticates to
# ECR, fetches the DB password from SSM Parameter Store, and starts the
# app container with --restart=always so it also survives instance
# reboots without this script running again.
set -euxo pipefail

dnf install -y docker
dnf clean all
systemctl enable --now docker

aws ecr get-login-password --region ${aws_region} \
  | docker login --username AWS --password-stdin ${ecr_registry}

# A fresh instance can occasionally win the docker pull race against
# ECR's eventual-consistency window for a just-pushed tag - a short
# retry loop is cheap insurance.
for i in 1 2 3 4 5; do
  docker pull ${image_uri} && break
  sleep 5
done

DB_PASSWORD=$(aws ssm get-parameter \
  --name "${db_password_param_name}" \
  --with-decryption \
  --region ${aws_region} \
  --query "Parameter.Value" \
  --output text)

# IMDSv2 is enforced on this launch template (metadata_options in
# asg.tf), so a token is required before reading instance metadata.
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/instance-id)

docker run -d --name sensible-debate --restart=always \
  -p 8000:8000 \
  -e SD_DATABASE_URL="postgresql+psycopg://${db_username}:$${DB_PASSWORD}@${db_endpoint}/${db_name}" \
  -e SD_REDIS_URL="redis://${redis_endpoint}:6379/0" \
  -e SD_ARGUMENT_SECONDS="${argument_seconds}" \
  -e SD_REFLECTION_SECONDS="${reflection_seconds}" \
  --log-driver=awslogs \
  --log-opt awslogs-region=${aws_region} \
  --log-opt awslogs-group=${log_group_name} \
  --log-opt awslogs-stream="$${INSTANCE_ID}" \
  --log-opt awslogs-create-group=false \
  ${image_uri}

