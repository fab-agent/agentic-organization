#!/bin/sh
# Attach to the workspace's agent session (used via `docker exec -it`).
# If the agent process has exited, restart it first.
set -eu
SESSION=${WORKSPACE_SESSION:-agent}
AGENT_CMD=${WORKSPACE_AGENT_CMD:-opencode}

workspace-session-start
if [ "$(tmux display-message -p -t "$SESSION" '#{pane_dead}')" = "1" ]; then
    tmux respawn-pane -k -t "$SESSION" -c /workspace "$AGENT_CMD"
fi
exec tmux attach-session -t "$SESSION"
