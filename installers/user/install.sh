#!/bin/sh
# User installer for Linux and macOS (ADR-0030).
#
# Puts four things on a workstation, all inside the user's home by default (no root, no
# system paths):
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

# Every temp file we create is registered here and removed on any exit or interrupt.
TMP1=""; TMP2=""
cleanup() { [ -z "$TMP1" ] || rm -f -- "$TMP1"; [ -z "$TMP2" ] || rm -f -- "$TMP2"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

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
[ "$UNINSTALL" -eq 0 ] || [ "$DRY" -eq 0 ] || die "--dry-run applies to installing only; nothing was removed"
[ "$UNINSTALL" -eq 1 ] || [ "$PURGE" -eq 0 ] || die "--purge-state belongs to --uninstall"

command -v node >/dev/null 2>&1 || die "Node.js 20 or newer is required (not found)"
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' \
  || die "Node.js 20 or newer is required (found $(node -v))"

[ -n "$STATE_DIR" ] || STATE_DIR="$HOME/.config/3pa/workspace"
[ -n "$APP_HOME" ] || APP_HOME="$HOME/.config/herdr-app"

# `link/` and `link/.` make the operating system follow a link that `link` would not; drop
# repeated, trailing and `.` components so every check and every write names the same thing.
norm() {
  printf '%s' "$1" | sed -e 's://*:/:g' -e 's:/\(\./\)\{1,\}:/:g' -e 's:/\.$::' -e 's:\(.\)/$:\1:'
}
PREFIX="$(norm "$PREFIX")"; STATE_DIR="$(norm "$STATE_DIR")"; APP_HOME="$(norm "$APP_HOME")"

# One place decides what a path may be. It works on the real locations (links resolved up to
# the deepest part that exists), so `..` and symlinks cannot disguise a dangerous target.
# Rules: absolute, no control characters or backslashes, never `/` or the home directory or a
# parent of it, and the four locations (bin, lib, state, app home) must not equal or contain
# one another - an uninstall or purge of one must never be able to take another with it.
check_paths() {
  P_HOME="$HOME" P_PREFIX="$PREFIX" P_STATE="$STATE_DIR" P_APP="$APP_HOME" node -e '
    const fs = require("fs"), path = require("path")
    const real = (p) => {
      let head = path.resolve(p), tail = []
      for (;;) {
        try { return path.join(fs.realpathSync(head), ...tail.reverse()) } catch (e) {
          if (e.code !== "ENOENT" && e.code !== "ENOTDIR") throw e
          const up = path.dirname(head); if (up === head) return head
          tail.push(path.basename(head)); head = up
        }
      }
    }
    const fail = (m) => { process.stderr.write(m + "\n"); process.exit(1) }
    const raw = { prefix: process.env.P_PREFIX, state: process.env.P_STATE, "app home": process.env.P_APP }
    const home = real(process.env.P_HOME)
    for (const [k, v] of Object.entries(raw)) {
      if (!path.isAbsolute(v)) fail(k + " path must be absolute")
      if (/[\x00-\x1f\x7f\\]/.test(v)) fail(k + " path must not contain control characters or backslashes")
      // `..` is resolved by the file system AFTER links, but by path.resolve BEFORE them: the
      // two can disagree, so a path that contains one is refused instead of interpreted.
      if (v.split("/").includes("..")) fail(k + " path must not contain ..")
    }
    // bin and lib are checked where they really are (either may itself be a link)
    const spots = {
      prefix: real(raw.prefix),
      bin: real(path.join(raw.prefix, "bin")), lib: real(path.join(raw.prefix, "lib", "3pa")),
      state: real(raw.state), "app home": real(raw["app home"]),
    }
    for (const [k, v] of Object.entries(spots)) {
      if (v === path.parse(v).root || v === home || home.startsWith(v + path.sep)) {
        fail(k + " location may not be / , your home directory or a parent of it")
      }
    }
    // the prefix only has to be a safe place to put bin/ and lib/ under; it may contain them
    delete spots.prefix
    const within = (a, b) => a === b || a.startsWith(b + path.sep)
    const names = Object.keys(spots)
    for (let i = 0; i < names.length; i++) for (let j = i + 1; j < names.length; j++) {
      if (within(spots[names[i]], spots[names[j]]) || within(spots[names[j]], spots[names[i]])) {
        fail(names[i] + " and " + names[j] + " locations overlap; choose separate folders")
      }
    }'
}
check_paths || die "unsafe location (see above)"

LIB="$PREFIX/lib/3pa"; BIN="$PREFIX/bin"

# Quote a value for a single-quoted shell string (the launcher is generated code). The
# trailing x keeps a final newline, which command substitution would otherwise drop.
sq() { printf "'%s'" "$(printf '%sx' "$1" | sed "s/'/'\\\\''/g")" | sed "s/x'\$/'/"; }

# Hash through stdin so file-name escaping in the tools can never alter the digest.
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum < "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 < "$1" | cut -d' ' -f1
  else die "neither sha256sum nor shasum found"; fi
}

# ── uninstall ────────────────────────────────────────────────────────────────
if [ "$UNINSTALL" -eq 1 ]; then
  for f in "$BIN/3pa" "$BIN/herdr-fab"; do
    if [ -e "$f" ] || [ -L "$f" ]; then rm -f -- "$f"; say "removed $f"; fi
  done
  # Only files this installer creates are removed, by name; folders go only if they end up empty.
  rm -f -- "$LIB/3pa.mjs" "$LIB/herdr"
  rmdir "$LIB" 2>/dev/null && say "removed $LIB" || true
  [ ! -d "$LIB" ] || say "kept $LIB (it holds files that are not ours)"
  if [ "$PURGE" -eq 1 ]; then
    # Exact names only, as the CLI and this installer create them; anything else in the folder
    # is somebody else's and stays. An unreadable folder is an error, not "nothing to do".
    STATE_DIR="$STATE_DIR" node -e '
      const fs = require("fs"), path = require("path")
      const dir = process.env.STATE_DIR
      const bad = (m) => { process.stderr.write("install.sh: " + m + "\n"); process.exit(1) }
      let d; try { d = fs.lstatSync(dir) } catch (e) {
        if (e.code === "ENOENT" || e.code === "ENOTDIR") { console.log("  no state folder at " + dir); process.exit(0) }
        bad("cannot inspect " + dir + " (" + e.code + "); nothing was removed") }
      if (d.isSymbolicLink() || !d.isDirectory()) bad(dir + " is a link or not a folder; nothing was removed")
      if (typeof process.getuid === "function" && d.uid !== process.getuid()) bad(dir + " belongs to someone else; nothing was removed")
      const OURS = [/^root\.pub$/, /^state\.json$/, /^state\.json\.replaced-\d+$/, /^state\.json\.[0-9a-f]{12}\.tmp$/,
        /^sync\.lock$/, /^sync\.lock\.takeover$/, /^sync\.lock(\.takeover)?\.tmp-[0-9a-f]{12}$/, /^\.root\.pub\.\d+\.tmp$/]
      let names; try { names = fs.readdirSync(dir) } catch (e) { bad("cannot read " + dir + " (" + e.code + "); nothing was removed") }
      let removed = 0, left = 0
      for (const n of names) {
        if (!OURS.some((r) => r.test(n))) { left++; continue }
        const p = path.join(dir, n)
        let s; try { s = fs.lstatSync(p) } catch (e) { bad("cannot inspect " + p + " (" + e.code + ")") }
        if (!s.isFile()) { left++; console.log("  left " + p + " (not a regular file)"); continue }
        try { fs.unlinkSync(p); removed++ } catch (e) { bad("cannot remove " + p + " (" + e.code + ")") }
      }
      try { fs.rmdirSync(dir); console.log("  removed " + dir + " (" + removed + " files: root key and sync history)") }
      catch (e) {
        if (e.code === "ENOTEMPTY" || e.code === "EEXIST") console.log("  removed " + removed + " file(s) of ours from " + dir + "; kept the folder (" + left + " other entries)")
        else bad("removed " + removed + " file(s) but could not remove the folder " + dir + " (" + e.code + ")")
      }' || exit 1
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

# The same rule as the CLI's checkBaseUrl (ADR-0029), on the parsed URL: https anywhere,
# http only for localhost / 127.0.0.1 / [::1]; no credentials, query or fragment.
BASE_URL="$(BASE_URL="$BASE_URL" node -e '
  const bad = (m) => { process.stderr.write(m + "\n"); process.exit(1) }
  const raw = process.env.BASE_URL
  let u; try { u = new URL(raw) } catch { bad("--base-url is not a valid platform URL (no credentials, query or fragment)") }
  const loop = u.hostname === "localhost" || u.hostname === "127.0.0.1" || u.hostname === "[::1]"
  if (u.protocol !== "https:" && !(u.protocol === "http:" && loop)) bad("--base-url must be https:// (http:// is accepted only for localhost)")
  if (u.username || u.password || u.search || u.hash || !u.hostname) bad("--base-url is not a valid platform URL (no credentials, query or fragment)")
  process.stdout.write(u.origin + u.pathname.replace(/\/+$/, ""))')" || exit 1

hex64() { printf %s "$1" | grep -Eq '^[0-9a-f]{64}$'; }
hex64 "$CLI_SHA" || die "--cli-sha256 must be 64 lowercase hex characters"
[ -z "$HERDR_SHA" ] || hex64 "$HERDR_SHA" || die "--herdr-sha256 must be 64 lowercase hex characters"

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

# What is at the state folder and at root.pub is looked at BEFORE anything is changed, and
# "cannot look" is never "not there": an unreadable pinned key stops the install.
ROOT_FILE="$STATE_DIR/root.pub"
EXISTING="$(STATE_DIR="$STATE_DIR" node -e '
  const fs = require("fs"), path = require("path")
  const bad = (m) => { process.stderr.write(m + "\n"); process.exit(1) }
  const look = (p) => { try { return fs.lstatSync(p) } catch (e) {
    if (e.code === "ENOENT" || e.code === "ENOTDIR") return null
    bad("cannot inspect " + p + " (" + e.code + "); nothing was changed") } }
  const dir = process.env.STATE_DIR
  const d = look(dir)
  if (d) {
    if (d.isSymbolicLink() || !d.isDirectory()) bad(dir + " is a link or not a folder; nothing was changed")
    if (typeof process.getuid === "function" && d.uid !== process.getuid()) bad(dir + " belongs to someone else; nothing was changed")
    const f = look(path.join(dir, "root.pub"))
    if (f) {
      if (!f.isFile()) bad(path.join(dir, "root.pub") + " is not a regular file; nothing was changed")
      let v; try { v = fs.readFileSync(path.join(dir, "root.pub"), "utf8") } catch (e) { bad("cannot read the pinned root key (" + e.code + "); nothing was changed") }
      process.stdout.write(v.replace(/[\r\n ]/g, ""))
    }
  }')" || exit 1
if [ -n "$EXISTING" ] && [ "$EXISTING" != "$ROOT_PUB" ] && [ "$REPLACE_ROOT" -ne 1 ]; then
  die "a different root key is already pinned in $ROOT_FILE; pass --replace-root only if the change is intended"
fi

# Every file we publish must be absent or a plain file: `mv` into a folder (or a link to one)
# would move the new file INSIDE it and still report success.
for f in "$LIB/3pa.mjs" "$LIB/herdr" "$BIN/3pa" "$BIN/herdr-fab"; do
  if [ -L "$f" ] || { [ -e "$f" ] && [ ! -f "$f" ]; }; then die "$f exists and is not a plain file; nothing was changed"; fi
done

if [ "$DRY" -eq 1 ]; then
  say "dry run on $OS: would install into $PREFIX (cli$( [ -n "$HERDR" ] && printf ', herdr, launcher')), state $STATE_DIR"
  exit 0
fi

# ── install ──────────────────────────────────────────────────────────────────
# Stage every artifact first: copy to a temp name next to its destination, then hash the COPY
# (a source swapped after the check cannot slip through). Nothing goes live until all of them
# match, so a wrong hash on the Herdr binary leaves the CLI and the key untouched as well.
mkdir -p "$BIN" "$LIB"
TMP1="$LIB/.3pa.mjs.$$.tmp"; rm -f -- "$TMP1"; cp "$CLI" "$TMP1"
[ "$(sha256_of "$TMP1")" = "$CLI_SHA" ] || die "SHA-256 of $CLI does not match; nothing was installed"
chmod 755 "$TMP1"
if [ -n "$HERDR" ]; then
  TMP2="$LIB/.herdr.$$.tmp"; rm -f -- "$TMP2"; cp "$HERDR" "$TMP2"
  [ "$(sha256_of "$TMP2")" = "$HERDR_SHA" ] || die "SHA-256 of $HERDR does not match; nothing was installed"
  chmod 755 "$TMP2"
fi

mkdir -p "$STATE_DIR"; chmod 700 "$STATE_DIR"

mv -f -- "$TMP1" "$LIB/3pa.mjs"; TMP1=""
say "installed 3pa bundle -> $LIB/3pa.mjs"

TMP1="$BIN/.3pa.$$.tmp"
printf '#!/bin/sh\nexec node %s "$@"\n' "$(sq "$LIB/3pa.mjs")" > "$TMP1"
chmod 755 "$TMP1"; mv -f -- "$TMP1" "$BIN/3pa"; TMP1=""
say "installed $BIN/3pa"

TMP1="$STATE_DIR/.root.pub.$$.tmp"
printf '%s\n' "$ROOT_PUB" > "$TMP1"
chmod 644 "$TMP1"; mv -f -- "$TMP1" "$ROOT_FILE"; TMP1=""
say "pinned root key -> $ROOT_FILE"

if [ -n "$HERDR" ]; then
  mv -f -- "$TMP2" "$LIB/herdr"; TMP2=""
  say "installed Herdr -> $LIB/herdr"
  # Fail closed: if the workspace cannot be synced and verified, Herdr is not started.
  TMP1="$BIN/.herdr-fab.$$.tmp"
  {
    printf '#!/bin/sh\n'
    printf 'set -eu\n'
    printf 'export FABAGENT_BASE_URL=%s\n' "$(sq "$BASE_URL")"
    printf 'export THREEPA_WORKSPACE_DIR=%s\n' "$(sq "$STATE_DIR")"
    printf 'export HERDR_APP_HOME=%s\n' "$(sq "$APP_HOME")"
    printf '%s workspace sync || { echo "herdr-fab: the workspace could not be synced and verified; not starting Herdr." >&2; exit 1; }\n' "$(sq "$BIN/3pa")"
    printf 'exec %s "$@"\n' "$(sq "$LIB/herdr")"
  } > "$TMP1"
  chmod 755 "$TMP1"; mv -f -- "$TMP1" "$BIN/herdr-fab"; TMP1=""
  say "installed launcher $BIN/herdr-fab"
else
  say "no Herdr binary given: installed the CLI and the root key only"
fi

case ":$PATH:" in *":$BIN:"*) ;; *) say "note: $BIN is not on PATH" ;; esac
say "done. First start: $( [ -n "$HERDR" ] && echo herdr-fab || echo '3pa workspace sync' ) (it asks you to sign in)"
