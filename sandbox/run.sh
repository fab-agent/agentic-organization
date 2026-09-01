#!/usr/bin/env bash
# Phase 0 stand-in for `3pa run` (ADR-0009). Builds the sandbox image and starts
# opencode inside it, with only the current project mounted.
#
# NOT production: no egress-proxy, no signature verification, no fail-closed
# heartbeat. Those arrive with the real `3pa` wrapper (ADR-0009 / ADR-0011).
#
# Usage:
#   FABAGENT_BASE_URL=https://agents.example.com \
#   FABAGENT_TOKEN=<persona token from POST /gateway/persona-token> \
#   FABAGENT_MODEL=fabagent/qwen-turbo \
#   sandbox/run.sh [project-dir]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(cd "${1:-$PWD}" && pwd)"
IMAGE="agentic-org-sandbox:dev"
ENGINE="${CONTAINER_ENGINE:-docker}"

: "${FABAGENT_BASE_URL:?set FABAGENT_BASE_URL}"
: "${FABAGENT_TOKEN:?set FABAGENT_TOKEN}"
FABAGENT_MODEL="${FABAGENT_MODEL:-fabagent/qwen-turbo}"

echo ">> building $IMAGE"
"$ENGINE" build -f "$REPO_ROOT/sandbox/Dockerfile" -t "$IMAGE" "$REPO_ROOT"

echo ">> starting opencode in sandbox (project: $PROJECT_DIR)"
exec "$ENGINE" run --rm -it \
  --network bridge \
  -v "$PROJECT_DIR:/work" \
  -e FABAGENT_BASE_URL \
  -e FABAGENT_TOKEN \
  -e FABAGENT_DEBUG \
  -e OPENCODE_MODEL="$FABAGENT_MODEL" \
  "$IMAGE" "$@"
