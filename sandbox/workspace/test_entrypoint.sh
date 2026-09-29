#!/bin/sh
# Behavioural test for entrypoint.sh / attach.sh without Docker: runs them with a
# fake "opencode" on a private tmux server. Needs tmux. Run: sh test_entrypoint.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'tmux -L wstest kill-server 2>/dev/null || true; kill "${ep:-0}" 2>/dev/null || true; rm -rf "$tmp"' EXIT

# Fake agent: records its env, then idles.
cat > "$tmp/opencode" <<FAKE
#!/bin/sh
env | sort > "$tmp/agent.env"
echo agent-started >> "$tmp/agent.log"
exec sleep 300
FAKE
chmod +x "$tmp/opencode"
# Private tmux socket so the test never touches a real session; /workspace is
# faked via a wrapper because the script hardcodes it.
mkdir -p "$tmp/bin"
cat > "$tmp/bin/tmux" <<WRAP
#!/bin/sh
exec $(command -v tmux) -L wstest "\$@"
WRAP
chmod +x "$tmp/bin/tmux"
sed "s#/workspace#$tmp/ws#g" "$here/entrypoint.sh" > "$tmp/entrypoint.sh"
sed "s#/workspace#$tmp/ws#g" "$here/attach.sh" > "$tmp/attach.sh"
sed "s#/workspace#$tmp/ws#g" "$here/session-start.sh" > "$tmp/workspace-session-start"
chmod +x "$tmp/workspace-session-start"

fail() { echo "FAIL: $1"; exit 1; }

PATH="$tmp/bin:$tmp:$PATH" \
OPENCODE_CONFIG=/evil OPENCODE_PERMISSION=allow OPENCODE_MODEL=fabagent/x \
FABAGENT_TOKEN=tok sh "$tmp/entrypoint.sh" &
ep=$!
sleep 1.5

PATH="$tmp/bin:$PATH" tmux has-session -t agent 2>/dev/null || fail "tmux session 'agent' not created"
[ -d "$tmp/ws/in" ] && [ -d "$tmp/ws/out" ] || fail "in/out dirs not created"
grep -q '^FABAGENT_TOKEN=tok$' "$tmp/agent.env" || fail "FABAGENT_TOKEN not passed to agent"
grep -q '^OPENCODE_MODEL=fabagent/x$' "$tmp/agent.env" || fail "OPENCODE_MODEL should be kept"
grep -q '^OPENCODE_CONFIG=' "$tmp/agent.env" && fail "OPENCODE_CONFIG must be scrubbed"
grep -q '^OPENCODE_PERMISSION=' "$tmp/agent.env" && fail "OPENCODE_PERMISSION must be scrubbed"
echo "ok: session created, env scrubbed, dirs created"

# The supervisor recreates the session if the tmux server dies.
PATH="$tmp/bin:$PATH" tmux kill-server
sleep 7
PATH="$tmp/bin:$PATH" tmux has-session -t agent 2>/dev/null || fail "session not recreated after server death"
[ "$(grep -c agent-started "$tmp/agent.log")" -ge 2 ] || fail "agent not restarted"
echo "ok: session recreated after tmux server death"

# 1) A missing session is recreated by attach.sh (attach itself needs a tty, so
# the final `exec tmux attach-session` is stubbed out).
sed 's#^exec tmux attach-session.*#echo attach-reached#' "$tmp/attach.sh" > "$tmp/attach-stub.sh"
PATH="$tmp/bin:$PATH" tmux kill-session -t agent
out=$(PATH="$tmp/bin:$tmp:$PATH" sh "$tmp/attach-stub.sh")
[ "$out" = "attach-reached" ] || fail "attach.sh did not reach attach"
PATH="$tmp/bin:$PATH" tmux has-session -t agent 2>/dev/null || fail "attach.sh did not recreate the session"
echo "ok: attach.sh recreates a missing session"

# 2) An agent that exited leaves a dead pane (remain-on-exit) that attach.sh respawns.
before=$(grep -c agent-started "$tmp/agent.log")
pid=$(PATH="$tmp/bin:$PATH" tmux list-panes -t agent -F '#{pane_pid}')
kill "$pid"
i=0; while [ "$(PATH="$tmp/bin:$PATH" tmux display-message -p -t agent '#{pane_dead}')" != "1" ] && [ $i -lt 20 ]; do sleep 0.2; i=$((i+1)); done
[ "$(PATH="$tmp/bin:$PATH" tmux display-message -p -t agent '#{pane_dead}')" = "1" ] || fail "pane did not stay dead (remain-on-exit not applied)"
out=$(PATH="$tmp/bin:$tmp:$PATH" sh "$tmp/attach-stub.sh")
[ "$out" = "attach-reached" ] || fail "attach.sh did not reach attach after respawn"
sleep 0.7
[ "$(PATH="$tmp/bin:$PATH" tmux display-message -p -t agent '#{pane_dead}')" = "0" ] || fail "dead pane was not respawned"
[ "$(grep -c agent-started "$tmp/agent.log")" -gt "$before" ] || fail "agent not restarted by respawn"
echo "ok: attach.sh respawns a dead pane"

# SIGTERM shuts the container's main process down promptly.
kill -TERM "$ep"
i=0; while kill -0 "$ep" 2>/dev/null && [ $i -lt 10 ]; do sleep 0.3; i=$((i+1)); done
kill -0 "$ep" 2>/dev/null && fail "entrypoint did not exit on SIGTERM"
echo "ok: exits on SIGTERM"
echo "ALL PASSED"
