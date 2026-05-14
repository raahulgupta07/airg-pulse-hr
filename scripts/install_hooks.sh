#!/usr/bin/env bash
# Install local git hooks for PULSE. Idempotent.
# Sets core.hooksPath to .githooks so the repo's hooks (including
# the destructive-migration linter) run on commit.
#
# Uninstall:
#   git config --unset core.hooksPath
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .githooks ]; then
  echo "error: .githooks directory missing" >&2
  exit 1
fi

chmod +x .githooks/* 2>/dev/null || true
git config core.hooksPath .githooks
echo "Installed: git core.hooksPath -> .githooks"
echo "Hooks active: $(/bin/ls .githooks | tr '\n' ' ')"
echo "Bypass any single commit with --no-verify (not recommended)."
