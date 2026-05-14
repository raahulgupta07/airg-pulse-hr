#!/usr/bin/env bash
# db-snapshot.sh — take a manual Aurora cluster snapshot.
#
# Usage:
#   ./db-snapshot.sh
#   ./db-snapshot.sh "before-major-migration"
#
# Env:
#   AWS_REGION       (default us-east-1)
#   ENV_NAME         (default prod)
#   RDS_CLUSTER_ID   (default pulse-$ENV_NAME)
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ENV_NAME="${ENV_NAME:-prod}"
RDS_CLUSTER_ID="${RDS_CLUSTER_ID:-pulse-${ENV_NAME}}"

LABEL="${1:-manual}"
LABEL_SAFE="$(echo "$LABEL" | tr -c 'A-Za-z0-9-' '-' | sed 's/-\+/-/g; s/^-//; s/-$//')"
TS=$(date -u +%Y%m%d-%H%M%S)
SNAP_ID="${RDS_CLUSTER_ID}-${LABEL_SAFE}-${TS}"

echo "==> Creating snapshot: $SNAP_ID"
aws rds create-db-cluster-snapshot \
  --region "$AWS_REGION" \
  --db-cluster-identifier "$RDS_CLUSTER_ID" \
  --db-cluster-snapshot-identifier "$SNAP_ID" >/dev/null

echo "==> Waiting for snapshot to become available (this can take several minutes)..."
aws rds wait db-cluster-snapshot-available \
  --region "$AWS_REGION" \
  --db-cluster-snapshot-identifier "$SNAP_ID"

echo "==> Snapshot ready: $SNAP_ID"
echo "    Restore example:"
echo "      aws rds restore-db-cluster-from-snapshot \\"
echo "        --db-cluster-identifier ${RDS_CLUSTER_ID}-restore \\"
echo "        --snapshot-identifier   $SNAP_ID \\"
echo "        --engine aurora-postgresql"
