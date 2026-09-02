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

# Fall back to the `3pa login` session if env vars aren't already set.
SESSION="${HOME}/.config/3pa/session.json"
if [ -z "${FABAGENT_TOKEN:-}" ] && [ -f "$SESSION" ] && command -v python3 >/dev/null; then
  FABAGENT_BASE_URL="${FABAGENT_BASE_URL:-$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["base_url"])' "$SESSION")}"
  FABAGENT_TOKEN="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["token"])' "$SESSION")"
  export FABAGENT_BASE_URL FABAGENT_TOKEN
fi

: "${FABAGENT_BASE_URL:?set FABAGENT_BASE_URL or run \`3pa login\`}"
: "${FABAGENT_TOKEN:?set FABAGENT_TOKEN or run \`3pa login\`}"
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
