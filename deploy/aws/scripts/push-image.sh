#!/usr/bin/env bash
# push-image.sh — manual ECR build & push (hotfix path; bypasses GitHub Actions).
#
# Usage:
#   ENV_NAME=prod ./push-image.sh                  # tag = git SHA + 'latest'
#   ENV_NAME=prod TAG=hotfix-2026-05-04 ./push-image.sh
#
# Required env:
#   AWS_REGION       (default us-east-1)
#   AWS_ACCOUNT_ID   (auto-detected via sts get-caller-identity if unset)
#   ECR_REPO         (default pulse-api)
#   ENV_NAME         (default prod) — used only for log readability
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ECR_REPO="${ECR_REPO:-pulse-api}"
ENV_NAME="${ENV_NAME:-prod}"
TAG="${TAG:-$(git rev-parse --short=12 HEAD)}"

REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${ECR_REPO}"

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

echo "==> ECR login  ($REGISTRY)"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> Ensuring buildx builder"
docker buildx inspect pulse-builder >/dev/null 2>&1 \
  || docker buildx create --name pulse-builder --use

echo "==> Building & pushing  $IMAGE:$TAG  (env=$ENV_NAME)"
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f "$ROOT/Dockerfile.prod" \
  -t "$IMAGE:$TAG" \
  -t "$IMAGE:latest" \
  --push \
  "$ROOT"

echo "==> Pushed.  To roll the service:"
echo "    aws ecs update-service --cluster pulse-$ENV_NAME --service pulse-api --force-new-deployment"
