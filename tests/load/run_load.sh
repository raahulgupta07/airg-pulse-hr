#!/bin/bash
# Usage: ./run_load.sh [users] [spawn_rate] [duration] [host]
#   users       default 100
#   spawn_rate  default 5  (users spawned per second)
#   duration    default 5m
#   host        default http://localhost:8090
#
# Outputs (in this directory):
#   report.html   - locust HTML report
#   stats_*.csv   - locust CSV stats
#
# Prereq: pip install locust
# Make sure backend has AGENT_V2=true and is reachable at $HOST.

set -euo pipefail

USERS=${1:-100}
SPAWN=${2:-5}
DURATION=${3:-5m}
HOST=${4:-http://localhost:8090}

cd "$(dirname "$0")"

if ! command -v locust >/dev/null 2>&1; then
  echo "ERROR: locust not found. Install with: pip install locust" >&2
  exit 1
fi

echo "==> Load test: users=$USERS spawn=$SPAWN duration=$DURATION host=$HOST"
locust -f locustfile.py \
  --headless \
  --users "$USERS" \
  --spawn-rate "$SPAWN" \
  --run-time "$DURATION" \
  --host "$HOST" \
  --html report.html \
  --csv stats
