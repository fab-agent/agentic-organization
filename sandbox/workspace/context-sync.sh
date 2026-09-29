#!/bin/sh
# Fetch this agent's company context (ADR-0020) into the file opencode reads as
# instructions: who it works for, the company, its department, its owner's job and
# the policies that apply. Installed as `workspace-context-sync`.
#
#   GET $FABAGENT_BASE_URL/workstation/context   (Accept: text/markdown, ETag cache)
#
# It never makes things worse: the file always exists (opencode is pointed at it),
# and on any failure — bad token, server down, oversized reply — the previous
# content is kept. Exit status is non-zero on failure, but callers must not treat
# that as fatal.
#
# The token is passed to curl on stdin, not on the command line, so it does not
# show up in `ps`.
set -u

FILE=${CONTEXT_FILE:-${HOME:-/home/agent}/.config/fab/context.md}
MAX_BYTES=65536
ETAG_FILE="$FILE.etag"

mkdir -p "$(dirname "$FILE")"
[ -f "$FILE" ] || : > "$FILE"

if [ -z "${FABAGENT_BASE_URL:-}" ] || [ -z "${FABAGENT_TOKEN:-}" ]; then
    echo "context-sync: FABAGENT_BASE_URL / FABAGENT_TOKEN not set" >&2
    exit 1
fi

tmp=$(mktemp "$FILE.XXXXXX") || exit 1
hdr=$(mktemp) || { rm -f "$tmp"; exit 1; }
trap 'rm -f "$tmp" "$hdr"' EXIT

cond=""
if [ -s "$ETAG_FILE" ]; then
    esc=$(sed 's/\\/\\\\/g; s/"/\\"/g' "$ETAG_FILE" | tr -d '\r\n')
    cond="header = \"If-None-Match: $esc\""
fi

code=$(printf 'header = "Authorization: Bearer %s"\nheader = "Accept: text/markdown"\n%s\n' \
        "$FABAGENT_TOKEN" "$cond" \
    | curl -sS -m 10 --max-filesize "$MAX_BYTES" -K - \
        -o "$tmp" -D "$hdr" -w '%{http_code}' \
        "$FABAGENT_BASE_URL/workstation/context") || {
    echo "context-sync: request failed — keeping the previous context" >&2
    exit 1
}

case "$code" in
    304)
        exit 0
        ;;
    200)
        size=$(wc -c < "$tmp" | tr -d ' ')
        if [ "$size" -eq 0 ] || [ "$size" -gt "$MAX_BYTES" ]; then
            echo "context-sync: unusable reply ($size bytes) — keeping the previous context" >&2
            exit 1
        fi
        etag=$(grep -i '^etag:' "$hdr" | tail -1 | sed 's/^[^:]*:[[:space:]]*//' | tr -d '\r\n')
        mv "$tmp" "$FILE"
        if [ -n "$etag" ]; then
            printf '%s' "$etag" > "$ETAG_FILE"
        else
            rm -f "$ETAG_FILE"
        fi
        echo "context-sync: updated ($size bytes)"
        ;;
    *)
        echo "context-sync: server answered HTTP $code — keeping the previous context" >&2
        exit 1
        ;;
esac
