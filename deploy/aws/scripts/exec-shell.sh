#!/usr/bin/env bash
# exec-shell.sh — open an interactive shell inside a running pulse-api task.
#
# Requires:
#   * ECS Exec enabled on the service (--enable-execute-command true).
#     Terraform sets this; if you change it manually you must force a new
#     deployment for it to take effect.
#   * IAM: caller needs ecs:ExecuteCommand and ssm:StartSession.
#   * SSM Session Manager plugin installed locally:
#       https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
#
# Usage:
#   ./exec-shell.sh                     # picks first RUNNING task
#   TASK_ID=abc123 ./exec-shell.sh      # specific task
#   CMD='/bin/bash' ./exec-shell.sh     # different shell
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ENV_NAME="${ENV_NAME:-prod}"
CLUSTER="${CLUSTER:-pulse-${ENV_NAME}}"
SERVICE="${SERVICE:-pulse-api}"
CONTAINER="${CONTAINER:-pulse-api}"
CMD="${CMD:-/bin/sh}"

if [[ -z "${TASK_ID:-}" ]]; then
  TASK_ID=$(aws ecs list-tasks \
    --region "$AWS_REGION" \
    --cluster "$CLUSTER" \
    --service-name "$SERVICE" \
    --desired-status RUNNING \
    --query 'taskArns[0]' --output text)
  [[ "$TASK_ID" == "None" || -z "$TASK_ID" ]] && { echo "no RUNNING tasks in $CLUSTER/$SERVICE"; exit 1; }
fi

echo "==> exec into $TASK_ID ($CONTAINER) — $CMD"
exec aws ecs execute-command \
  --region "$AWS_REGION" \
  --cluster "$CLUSTER" \
  --task "$TASK_ID" \
  --container "$CONTAINER" \
  --interactive \
  --command "$CMD"
