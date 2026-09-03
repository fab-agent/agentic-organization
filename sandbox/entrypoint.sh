#!/bin/sh
# Sandbox entrypoint (ADR-0002 / ADR-0011).
#
# Strip any OPENCODE_* env var the host may have set — `OPENCODE_CONFIG`,
# `OPENCODE_PERMISSION`, `OPENCODE_CONFIG_CONTENT`, … can override the managed
# `/etc/opencode/opencode.json`. Only `OPENCODE_MODEL` (the model selector `3pa`
# passes) is kept.
set -eu

vars=$(env | sed -n 's/^\(OPENCODE_[A-Za-z0-9_]*\)=.*/\1/p')
for k in $vars; do
    [ "$k" = "OPENCODE_MODEL" ] || unset "$k"
done

exec opencode "$@"
