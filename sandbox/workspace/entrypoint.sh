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

# Company context for opencode (ADR-0020): fetched before the agent starts, then
# refreshed periodically. A failure is never fatal — the previous file stays.
refresh=${WORKSPACE_CONTEXT_REFRESH_SECONDS:-300}
every=$((refresh / 5))
[ "$every" -ge 1 ] || every=1
sync_context() {
    workspace-context-sync || echo "entrypoint: company context not refreshed" >&2
}

stop() {
    tmux kill-server 2>/dev/null || true
    exit 0
}
trap stop TERM INT

sync_context
start_session
i=0
while :; do
    tmux has-session -t "$SESSION" 2>/dev/null || start_session
    i=$((i + 1))
    [ $((i % every)) -eq 0 ] && sync_context
    sleep 5 &
    wait $! || true
done
