#!/usr/bin/env bash
# tail-logs.sh — follow CloudWatch logs for the pulse-api ECS service.
#
# Usage:
#   ./tail-logs.sh                      # follow live
#   SINCE=30m ./tail-logs.sh            # start 30 min ago
#   FILTER='ERROR' ./tail-logs.sh       # only lines containing ERROR
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ENV_NAME="${ENV_NAME:-prod}"
LOG_GROUP="${LOG_GROUP:-/ecs/pulse-api-${ENV_NAME}}"
SINCE="${SINCE:-5m}"

EXTRA=()
[[ -n "${FILTER:-}" ]] && EXTRA+=(--filter-pattern "$FILTER")

exec aws logs tail "$LOG_GROUP" \
  --region "$AWS_REGION" \
  --follow \
  --format short \
  --since "$SINCE" \
  "${EXTRA[@]}"
