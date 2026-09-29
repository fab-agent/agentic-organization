#!/bin/sh
# Workspace entrypoint (ADR-0018).
#
# Keeps one tmux session ("agent") running opencode, restarting it if the tmux
# server ever disappears, and stays in the foreground as the container's main
# process. Clients attach with `workspace-attach`; a dropped connection only
# detaches, it never stops the agent.
#
# Like sandbox/entrypoint.sh (ADR-0002 / ADR-0011): strip OPENCODE_* env vars the
# host may have set so nobody can override /etc/opencode/opencode.json. Only
# OPENCODE_MODEL is kept.
set -eu

SESSION=${WORKSPACE_SESSION:-agent}

vars=$(env | sed -n 's/^\(OPENCODE_[A-Za-z0-9_]*\)=.*/\1/p')
for k in $vars; do
    [ "$k" = "OPENCODE_MODEL" ] || unset "$k"
done

mkdir -p /workspace/in /workspace/out

start_session() {
    workspace-session-start
}

stop() {
    tmux kill-server 2>/dev/null || true
    exit 0
}
trap stop TERM INT

start_session
while :; do
    tmux has-session -t "$SESSION" 2>/dev/null || start_session
    sleep 5 &
    wait $! || true
done
