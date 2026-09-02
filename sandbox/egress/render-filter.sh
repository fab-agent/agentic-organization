#!/bin/sh
# Render a tinyproxy filter file — one POSIX-extended regex per line — from:
#   - the baked-in base allowlist ($1, default /etc/egress/base-allowlist.txt)
#   - $EGRESS_ALLOWLIST         : extra hosts, comma / space / newline separated
#   - the host of $FABAGENT_BASE_URL : the LLM gateway (ADR-0004)
#
# Each host becomes a suffix match: "github.com" -> (^|\.)github\.com$ , which
# allows github.com and *.github.com but not evilgithub.com. A leading "*." or
# "." is stripped; "#" comments and blank lines are ignored; duplicates collapse.
#
# tinyproxy is configured FilterDefaultDeny — anything not emitted here is denied
# (ADR-0010). See sandbox/egress/README.md.
set -eu

base="${1:-/etc/egress/base-allowlist.txt}"

{
  if [ -f "$base" ]; then cat "$base"; fi
  printf '%s\n' "${EGRESS_ALLOWLIST:-}" | tr ',;\t ' '\n'
  if [ -n "${FABAGENT_BASE_URL:-}" ]; then
    printf '%s\n' "$FABAGENT_BASE_URL" |
      sed -e 's#^[a-zA-Z][a-zA-Z0-9+.-]*://##' -e 's#[/?].*$##' -e 's#:[0-9]*$##' -e 's#.*@##'
  fi
} | awk '
  {
    sub(/#.*/, "")
    gsub(/[ \t\r]/, "")
  }
  /^$/ { next }
  {
    sub(/^\*\./, "")
    sub(/^\.+/, "")
  }
  /^$/ { next }
  !seen[tolower($0)]++ {
    host = tolower($0)
    esc = ""
    n = split(host, ch, "")
    for (i = 1; i <= n; i++) {
      c = ch[i]
      if (index(".[]()*+?^$|\\{}", c) > 0) esc = esc "\\" c
      else esc = esc c
    }
    printf "(^|\\.)%s$\n", esc
  }
'
