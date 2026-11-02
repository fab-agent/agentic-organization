#!/bin/sh
# Run the deployment helper (ADR-0033) for the person who uses this Mac / Linux machine.
#   sh deploy.sh install|check --config deploy.conf [--user NAME]
# Started by an MDM / Ansible as root, it switches to the logged-in user (macOS: the console
# user; elsewhere pass --user). Started as an ordinary user (a login script) it acts for that
# user and refuses --user for anybody else. The installer itself never runs as root.
set -eu

die() { printf 'deploy.sh: %s\n' "$*" >&2; exit "${2:-1}"; }

[ $# -ge 1 ] || die "usage: deploy.sh install|check --config FILE [--user NAME]" 2
CMD="$1"; shift
CONF=""; TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config) [ $# -ge 2 ] || die "--config needs a value" 2; CONF="$2"; shift 2 ;;
    --user) [ $# -ge 2 ] || die "--user needs a value" 2; TARGET="$2"; shift 2 ;;
    *) die "unknown option: $1" 2 ;;
  esac
done
[ -n "$CONF" ] && [ -f "$CONF" ] || die "--config FILE is required and must exist" 2
HERE="$(cd "$(dirname "$0")" && pwd)"
CONF="$(cd "$(dirname "$CONF")" && pwd)/$(basename "$CONF")"
command -v node >/dev/null 2>&1 || die "Node.js 20 or newer is required (not found)" 2

if [ "$(id -u)" -eq 0 ]; then
  if [ -z "$TARGET" ] && [ "$(uname -s)" = "Darwin" ]; then TARGET="$(stat -f %Su /dev/console)"; fi
  [ -n "$TARGET" ] || die "running as root: say which user with --user NAME" 2
  case "$TARGET" in root|"") die "refusing to install for root; nobody is logged in?" 3 ;; esac
  case "$TARGET" in *[!A-Za-z0-9._-]*) die "unusual user name: $TARGET" 2 ;; esac
  id "$TARGET" >/dev/null 2>&1 || die "no such user: $TARGET" 2
  if [ "$(uname -s)" = "Darwin" ]; then
    UHOME="$(dscl . -read "/Users/$TARGET" NFSHomeDirectory | awk '{print $2}')"
  else
    UHOME="$(getent passwd "$TARGET" | cut -d: -f6)"
  fi
  [ -n "$UHOME" ] && [ -d "$UHOME" ] || die "$TARGET has no home directory" 2
  if command -v runuser >/dev/null 2>&1; then
    exec runuser -u "$TARGET" -- env -i HOME="$UHOME" PATH="$PATH" node "$HERE/deploy.mjs" "$CMD" --config "$CONF"
  fi
  exec sudo -n -u "$TARGET" -H env -i HOME="$UHOME" PATH="$PATH" node "$HERE/deploy.mjs" "$CMD" --config "$CONF"
fi
if [ -n "$TARGET" ] && [ "$TARGET" != "$(id -un)" ]; then
  die "running as $(id -un): cannot act for $TARGET (run as root to switch users)" 3
fi
exec node "$HERE/deploy.mjs" "$CMD" --config "$CONF"
