#!/bin/sh
# User installer for Linux and macOS (ADR-0030).
#
# Puts four things on a workstation, all inside the user's home (no root, no system paths):
#   1. the `3pa` CLI bundle, checked against a SHA-256 you pass in,
#   2. the pinned root public key (never fetched from the server),
#   3. optionally the Herdr app binary, also checked against a SHA-256 you pass in,
#   4. a `herdr-fab` launcher that syncs the signed workspace and then starts Herdr.
#
# It does not download anything. The administrator (or MDM) hands it the files and the
# hashes; a download step with its own trust root is a later slice.
#
# Usage:
#   install.sh --base-url URL --root-pub FILE|BASE64 --cli FILE --cli-sha256 HEX
#              [--herdr-bin FILE --herdr-sha256 HEX] [--prefix DIR] [--app-home DIR]
#              [--state-dir DIR] [--replace-root] [--dry-run]
#   install.sh --uninstall [--prefix DIR] [--state-dir DIR] [--purge-state]

set -eu
umask 077

die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }
say() { printf '  %s\n' "$*"; }

BASE_URL=""; ROOT_PUB=""; CLI=""; CLI_SHA=""; HERDR=""; HERDR_SHA=""
PREFIX="${HOME:-}/.local"; APP_HOME=""; STATE_DIR=""
REPLACE_ROOT=0; DRY=0; UNINSTALL=0; PURGE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --base-url) [ $# -ge 2 ] || die "$1 needs a value"; BASE_URL="$2"; shift 2 ;;
    --root-pub) [ $# -ge 2 ] || die "$1 needs a value"; ROOT_PUB="$2"; shift 2 ;;
    --cli) [ $# -ge 2 ] || die "$1 needs a value"; CLI="$2"; shift 2 ;;
    --cli-sha256) [ $# -ge 2 ] || die "$1 needs a value"; CLI_SHA="$2"; shift 2 ;;
    --herdr-bin) [ $# -ge 2 ] || die "$1 needs a value"; HERDR="$2"; shift 2 ;;
    --herdr-sha256) [ $# -ge 2 ] || die "$1 needs a value"; HERDR_SHA="$2"; shift 2 ;;
    --prefix) [ $# -ge 2 ] || die "$1 needs a value"; PREFIX="$2"; shift 2 ;;
    --app-home) [ $# -ge 2 ] || die "$1 needs a value"; APP_HOME="$2"; shift 2 ;;
    --state-dir) [ $# -ge 2 ] || die "$1 needs a value"; STATE_DIR="$2"; shift 2 ;;
    --replace-root) REPLACE_ROOT=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --purge-state) PURGE=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

# ── platform and user ────────────────────────────────────────────────────────
case "$(uname -s)" in
  Linux) OS=linux ;;
  Darwin) OS=macos ;;
  *) die "unsupported system $(uname -s): this installer covers Linux and macOS" ;;
esac
[ "$(id -u)" -ne 0 ] || die "run as the person who will use the workspace, not as root"
[ -n "${HOME:-}" ] && [ -d "$HOME" ] || die "HOME is not set to an existing directory"

case "$PREFIX" in /*) ;; *) die "--prefix must be an absolute path" ;; esac
[ -n "$STATE_DIR" ] || STATE_DIR="$HOME/.config/3pa/workspace"
[ -n "$APP_HOME" ] || APP_HOME="$HOME/.config/herdr-app"
for d in "$STATE_DIR" "$APP_HOME"; do
  case "$d" in /*) ;; *) die "paths must be absolute: $d" ;; esac
done

LIB="$PREFIX/lib/3pa"; BIN="$PREFIX/bin"

# Quote a value for a single-quoted shell string (the launcher is generated code).
sq() { printf "'%s'" "$(printf %s "$1" | sed "s/'/'\\\\''/g")"; }

# ── uninstall ────────────────────────────────────────────────────────────────
if [ "$UNINSTALL" -eq 1 ]; then
  for f in "$BIN/3pa" "$BIN/herdr-fab"; do
    if [ -e "$f" ] || [ -L "$f" ]; then rm -f "$f"; say "removed $f"; fi
  done
  [ -d "$LIB" ] && { rm -rf "$LIB"; say "removed $LIB"; }
  if [ "$PURGE" -eq 1 ]; then
    [ -d "$STATE_DIR" ] && { rm -rf "$STATE_DIR"; say "removed $STATE_DIR (root key and sync history)"; }
  else
    say "kept $STATE_DIR (root key and sync history; --purge-state removes it)"
  fi
  say "left the Herdr app home alone: $APP_HOME"
  exit 0
fi

# ── inputs ───────────────────────────────────────────────────────────────────
[ -n "$BASE_URL" ] || die "--base-url is required"
[ -n "$ROOT_PUB" ] || die "--root-pub is required"
[ -n "$CLI" ] && [ -n "$CLI_SHA" ] || die "--cli and --cli-sha256 are required"
if [ -n "$HERDR" ] || [ -n "$HERDR_SHA" ]; then
  [ -n "$HERDR" ] && [ -n "$HERDR_SHA" ] || die "--herdr-bin and --herdr-sha256 go together"
fi

command -v node >/dev/null 2>&1 || die "Node.js 20 or newer is required (not found)"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' \
  || die "Node.js 20 or newer is required (found $(node -v))"

# The URL rule is the one the CLI enforces (ADR-0029): https anywhere, http only for loopback.
case "$BASE_URL" in
  https://*) ;;
  http://localhost|http://localhost/*|http://localhost:*|http://127.0.0.1|http://127.0.0.1/*|http://127.0.0.1:*|"http://[::1]"|"http://[::1]/"*|"http://[::1]:"*) ;;
  *) die "--base-url must be https:// (http:// is accepted only for localhost)" ;;
esac
BASE_URL="$(BASE_URL="$BASE_URL" node -e '
  try {
    const u = new URL(process.env.BASE_URL)
    if (u.username || u.password || u.search || u.hash) process.exit(1)
    process.stdout.write(u.origin + u.pathname.replace(/\/+$/, ""))
  } catch { process.exit(1) }')" || die "--base-url is not a valid platform URL (no credentials, query or fragment)"

hex64() { printf %s "$1" | grep -Eq '^[0-9a-f]{64}$'; }
hex64 "$CLI_SHA" || die "--cli-sha256 must be 64 lowercase hex characters"
[ -z "$HERDR_SHA" ] || hex64 "$HERDR_SHA" || die "--herdr-sha256 must be 64 lowercase hex characters"

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  else die "neither sha256sum nor shasum found"; fi
}

# Root key: a file or the base64 itself; exactly the 32 raw bytes of an Ed25519 public key,
# in canonical base64.
if [ -f "$ROOT_PUB" ]; then ROOT_PUB="$(tr -d '\r\n ' < "$ROOT_PUB")"; fi
ROOT_PUB="$(printf %s "$ROOT_PUB" | tr -d '\r\n ')"
ROOT_PUB="$ROOT_PUB" node -e '
  const s = process.env.ROOT_PUB
  const b = Buffer.from(s, "base64")
  process.exit(b.length === 32 && b.toString("base64") === s ? 0 : 1)' \
  || die "--root-pub is not a valid Ed25519 public key (32 bytes, canonical base64)"

[ -f "$CLI" ] && [ ! -L "$CLI" ] || die "--cli must be a regular file"
if [ -n "$HERDR" ]; then [ -f "$HERDR" ] && [ ! -L "$HERDR" ] || die "--herdr-bin must be a regular file"; fi

# An existing, different root key is a change of trust: never silently.
ROOT_FILE="$STATE_DIR/root.pub"
if [ -f "$ROOT_FILE" ]; then
  if [ "$(tr -d '\r\n ' < "$ROOT_FILE")" != "$ROOT_PUB" ] && [ "$REPLACE_ROOT" -ne 1 ]; then
    die "a different root key is already pinned in $ROOT_FILE; pass --replace-root only if the change is intended"
  fi
fi

if [ "$DRY" -eq 1 ]; then
  say "dry run on $OS: would install into $PREFIX (cli$( [ -n "$HERDR" ] && printf ', herdr, launcher')), state $STATE_DIR"
  exit 0
fi

# ── install ──────────────────────────────────────────────────────────────────
# Copy first, then hash the COPY: a source that changes after the check cannot slip through.
install_checked() { # src sha dest mode
  tmp="$(dirname "$3")/.$(basename "$3").$$.tmp"
  mkdir -p "$(dirname "$3")"
  rm -f "$tmp"
  cp "$1" "$tmp"
  if [ "$(sha256_of "$tmp")" != "$2" ]; then rm -f "$tmp"; die "SHA-256 of $1 does not match; nothing was installed from it"; fi
  chmod "$4" "$tmp"
  mv -f "$tmp" "$3"
}

mkdir -p "$STATE_DIR" "$BIN" "$LIB"
chmod 700 "$STATE_DIR"
[ ! -L "$STATE_DIR" ] || die "$STATE_DIR is a symbolic link"

install_checked "$CLI" "$CLI_SHA" "$LIB/3pa.mjs" 755
say "installed 3pa bundle -> $LIB/3pa.mjs"

printf '#!/bin/sh\nexec node %s "$@"\n' "$(sq "$LIB/3pa.mjs")" > "$BIN/.3pa.$$.tmp"
chmod 755 "$BIN/.3pa.$$.tmp"; mv -f "$BIN/.3pa.$$.tmp" "$BIN/3pa"
say "installed $BIN/3pa"

printf '%s\n' "$ROOT_PUB" > "$STATE_DIR/.root.pub.$$.tmp"
chmod 644 "$STATE_DIR/.root.pub.$$.tmp"; mv -f "$STATE_DIR/.root.pub.$$.tmp" "$ROOT_FILE"
say "pinned root key -> $ROOT_FILE"

if [ -n "$HERDR" ]; then
  install_checked "$HERDR" "$HERDR_SHA" "$LIB/herdr" 755
  say "installed Herdr -> $LIB/herdr"
  # Fail closed: if the workspace cannot be synced and verified, Herdr is not started.
  {
    printf '#!/bin/sh\n'
    printf 'set -eu\n'
    printf 'export FABAGENT_BASE_URL=%s\n' "$(sq "$BASE_URL")"
    printf 'export THREEPA_WORKSPACE_DIR=%s\n' "$(sq "$STATE_DIR")"
    printf 'export HERDR_APP_HOME=%s\n' "$(sq "$APP_HOME")"
    printf '%s workspace sync || { echo "herdr-fab: the workspace could not be synced and verified; not starting Herdr." >&2; exit 1; }\n' "$(sq "$BIN/3pa")"
    printf 'exec %s "$@"\n' "$(sq "$LIB/herdr")"
  } > "$BIN/.herdr-fab.$$.tmp"
  chmod 755 "$BIN/.herdr-fab.$$.tmp"; mv -f "$BIN/.herdr-fab.$$.tmp" "$BIN/herdr-fab"
  say "installed launcher $BIN/herdr-fab"
else
  say "no Herdr binary given: installed the CLI and the root key only"
fi

case ":$PATH:" in *":$BIN:"*) ;; *) say "note: $BIN is not on PATH" ;; esac
say "done. First start: $( [ -n "$HERDR" ] && echo herdr-fab || echo '3pa workspace sync' ) (it asks you to sign in)"
