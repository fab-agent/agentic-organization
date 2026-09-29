#!/bin/sh
# Create the agent's tmux session with the workspace options (idempotent).
# Shared by entrypoint.sh and attach.sh so a session made by either behaves the
# same: remain-on-exit keeps the last output visible when the agent exits.
set -eu
SESSION=${WORKSPACE_SESSION:-agent}
AGENT_CMD=${WORKSPACE_AGENT_CMD:-opencode}

tmux has-session -t "$SESSION" 2>/dev/null && exit 0
tmux new-session -d -s "$SESSION" -x 200 -y 50 -c /workspace "$AGENT_CMD"
tmux set-option -t "$SESSION" remain-on-exit on
tmux set-option -t "$SESSION" history-limit 20000
tmux set-option -t "$SESSION" status off
