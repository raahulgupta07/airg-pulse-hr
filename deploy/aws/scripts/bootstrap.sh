#!/usr/bin/env bash
# bootstrap.sh — one-time AWS bootstrap for HUB-HR-Agent (pulse).
#
#   1. terraform init && terraform apply
#   2. prompt for the SUPERADMIN password, bcrypt-hash it inside the prod
#      container, and store the hash in Secrets Manager.
#
# Idempotent: re-running re-applies terraform (no-op if no diff) and
# overwrites the secret value.
#
# Required env (or pass on command line):
#   ENV_NAME      e.g. prod | staging          (default: prod)
#   AWS_REGION    e.g. us-east-1               (default: us-east-1)
#   IMAGE         local prod image to use for hashing
#                                              (default: pulse:latest)
set -euo pipefail

ENV_NAME="${ENV_NAME:-prod}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE="${IMAGE:-pulse:latest}"
SECRET_NAME="pulse/${ENV_NAME}/superadmin_pass_hash"

ROOT="$(cd "$(dirname "$0")/../terraform" && pwd)"

echo "==> terraform init   ($ROOT)"
terraform -chdir="$ROOT" init -upgrade

echo "==> terraform apply  (env=$ENV_NAME)"
terraform -chdir="$ROOT" apply -var "env_name=$ENV_NAME" -var "aws_region=$AWS_REGION"

echo
echo "==> Set SUPERADMIN password"
read -rsp "  New SUPERADMIN password: "  PW1; echo
read -rsp "  Confirm:                "    PW2; echo
[[ "$PW1" == "$PW2" ]] || { echo "passwords do not match"; exit 1; }
[[ ${#PW1} -ge 12 ]]   || { echo "password must be >= 12 chars"; exit 1; }

echo "==> Generating bcrypt hash via $IMAGE"
HASH=$(docker run --rm -i "$IMAGE" python -m backend.scripts.hash_pw "$PW1")
[[ "$HASH" =~ ^\$2[aby]\$ ]] || { echo "hash_pw did not return a bcrypt hash"; exit 1; }

echo "==> Writing secret $SECRET_NAME ($AWS_REGION)"
if aws secretsmanager describe-secret --region "$AWS_REGION" --secret-id "$SECRET_NAME" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value \
    --region "$AWS_REGION" \
    --secret-id "$SECRET_NAME" \
    --secret-string "$HASH" >/dev/null
else
  aws secretsmanager create-secret \
    --region "$AWS_REGION" \
    --name "$SECRET_NAME" \
    --secret-string "$HASH" >/dev/null
fi

echo "==> Done. Force a new ECS deployment to pick up the new hash:"
echo "    aws ecs update-service --cluster pulse-$ENV_NAME --service pulse-api --force-new-deployment"
