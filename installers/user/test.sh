#!/bin/sh
# Tests for install.sh. Runs in a throw-away HOME; touches nothing else.
set -u
# The installer refuses to run as root, so a root run of this file re-executes itself as an
# unprivileged user (and checks the refusal first).
if [ "$(id -u)" -eq 0 ]; then
  H="$(cd "$(dirname "$0")" && pwd)"
  out="$(sh "$H/install.sh" --base-url https://x.example 2>&1)"; rc=$?
  { [ $rc -ne 0 ] && printf %s "$out" | grep -q "not as root"; } || { echo "FAIL: root must be refused ($out)"; exit 1; }
  D="$(mktemp -d)"; cp "$H/install.sh" "$H/test.sh" "$D/"; mkdir "$D/bin"
  # node may live somewhere the unprivileged user cannot reach (e.g. under /root): give it a copy
  cp "$(readlink -f "$(command -v node)")" "$D/bin/node"
  chmod -R a+rX "$D"; chmod a+rx "$D"
  if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid=65534 --regid=65534 --clear-groups env HOME=/nonexistent PATH="$D/bin:/usr/bin:/bin" sh "$D/test.sh"
  fi
  exec su -s /bin/sh nobody -c "PATH=$D/bin:/usr/bin:/bin sh $D/test.sh"
fi
HERE="$(cd "$(dirname "$0")" && pwd)"; INST="$HERE/install.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); }
bad() { FAIL=$((FAIL+1)); printf 'FAIL: %s\n' "$1"; }
expect_fail() { # name, grep-pattern, cmd...
  n="$1"; pat="$2"; shift 2
  out="$("$@" 2>&1)"; rc=$?
  if [ $rc -ne 0 ] && printf %s "$out" | grep -q -- "$pat"; then ok; else bad "$n (rc=$rc: $out)"; fi
}
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

export HOME="$T/home"; mkdir -p "$HOME"
printf 'console.log("3pa-stub", process.argv.slice(2).join(" "))\n' > "$T/3pa.mjs"
printf '#!/bin/sh\necho "herdr-stub home=$HERDR_APP_HOME $*"\n' > "$T/herdr"; chmod +x "$T/herdr"
KEY="$(node -e 'process.stdout.write(Buffer.alloc(32,7).toString("base64"))')"
OTHER="$(node -e 'process.stdout.write(Buffer.alloc(32,9).toString("base64"))')"
CS="$(sha "$T/3pa.mjs")"; HS="$(sha "$T/herdr")"
B="https://platform.example"
base() { sh "$INST" --base-url "$B" --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$CS" "$@"; }

# refusals
expect_fail "missing args" "required" sh "$INST"
expect_fail "http remote" "https" sh "$INST" --base-url http://platform.example --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$CS"
expect_fail "lookalike localhost" "https" sh "$INST" --base-url http://localhost.evil.example --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$CS"
expect_fail "credentials in url" "valid platform URL" sh "$INST" --base-url "https://u:p@platform.example" --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$CS"
expect_fail "query in url" "valid platform URL" sh "$INST" --base-url "https://platform.example/?a=1" --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$CS"
expect_fail "short root key" "Ed25519" sh "$INST" --base-url "$B" --root-pub "AAAA" --cli "$T/3pa.mjs" --cli-sha256 "$CS"
expect_fail "non-canonical root key" "Ed25519" sh "$INST" --base-url "$B" --root-pub "${KEY%=}" --cli "$T/3pa.mjs" --cli-sha256 "$CS"
expect_fail "bad hash format" "64 lowercase" sh "$INST" --base-url "$B" --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 abc
expect_fail "herdr bin without hash" "go together" base --herdr-bin "$T/herdr"
expect_fail "relative prefix" "absolute" base --prefix rel
ln -s "$T/3pa.mjs" "$T/link.mjs"
expect_fail "symlink source" "regular file" sh "$INST" --base-url "$B" --root-pub "$KEY" --cli "$T/link.mjs" --cli-sha256 "$CS"
expect_fail "unknown option" "unknown option" base --nope

# wrong hash installs nothing, leaves no temp file
expect_fail "wrong cli hash" "does not match" sh "$INST" --base-url "$B" --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$(printf 0%.0s $(seq 64))"
[ ! -e "$HOME/.local/lib/3pa/3pa.mjs" ] && ok || bad "wrong hash left a bundle"
[ -z "$(ls -A "$HOME/.local/lib/3pa" 2>/dev/null)" ] && ok || bad "wrong hash left temp files"

# dry run writes nothing
base --dry-run --prefix "$T/dry" --state-dir "$T/dry-st" >/dev/null 2>&1 && [ ! -e "$T/dry" ] && [ ! -e "$T/dry-st" ] && ok || bad "dry run wrote files"

# full install
out="$(base --herdr-bin "$T/herdr" --herdr-sha256 "$HS" 2>&1)" && ok || bad "install failed: $out"
[ -x "$HOME/.local/bin/3pa" ] && [ -x "$HOME/.local/bin/herdr-fab" ] && ok || bad "missing binaries"
[ "$("$HOME/.local/bin/3pa" workspace status)" = "3pa-stub workspace status" ] && ok || bad "wrapper does not run the bundle"
[ "$(cat "$HOME/.config/3pa/workspace/root.pub")" = "$KEY" ] && ok || bad "root key not pinned"
perm() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }
[ "$(perm "$HOME/.config/3pa/workspace")" = "700" ] && ok || bad "state dir not 0700"
[ "$(perm "$HOME/.local/lib/3pa/3pa.mjs")" = "755" ] && ok || bad "bundle mode"
if grep -q "FABAGENT_BASE_URL='$B'" "$HOME/.local/bin/herdr-fab" && grep -q "HERDR_APP_HOME='$HOME/.config/herdr-app'" "$HOME/.local/bin/herdr-fab"; then ok; else bad "launcher env"; fi
ls -A "$HOME/.local/bin" "$HOME/.local/lib/3pa" | grep -q '\.tmp' && bad "temp files left" || ok

# the launcher syncs, then starts Herdr; and refuses to start Herdr when the sync fails
lo="$("$HOME/.local/bin/herdr-fab" --x 2>&1)"
printf %s "$lo" | grep -q "3pa-stub workspace sync" && printf %s "$lo" | grep -q "herdr-stub home=$HOME/.config/herdr-app --x" && ok || bad "launcher flow: $lo"
printf 'process.exit(3)\n' > "$HOME/.local/lib/3pa/3pa.mjs"
lo="$("$HOME/.local/bin/herdr-fab" 2>&1)"; rc=$?
[ $rc -ne 0 ] && ! printf %s "$lo" | grep -q "herdr-stub" && printf %s "$lo" | grep -q "not starting Herdr" && ok || bad "launcher must fail closed: rc=$rc $lo"

# a path with a quote and a space survives the generated launcher
Q="$T/it's here"; mkdir -p "$Q"
base --herdr-bin "$T/herdr" --herdr-sha256 "$HS" --prefix "$Q" --state-dir "$Q/st" --app-home "$Q/app" >/dev/null 2>&1 && ok || bad "quote path install"
[ "$("$Q/bin/herdr-fab" 2>&1 | tail -1)" = "herdr-stub home=$Q/app " ] && ok || bad "quote path launcher: $("$Q/bin/herdr-fab" 2>&1)"

# a different root key is refused unless replacement is explicit
expect_fail "root swap" "different root key" sh "$INST" --base-url "$B" --root-pub "$OTHER" --cli "$T/3pa.mjs" --cli-sha256 "$CS"
sh "$INST" --base-url "$B" --root-pub "$OTHER" --cli "$T/3pa.mjs" --cli-sha256 "$CS" --replace-root >/dev/null 2>&1 && [ "$(cat "$HOME/.config/3pa/workspace/root.pub")" = "$OTHER" ] && ok || bad "explicit root replacement"

# root key from a file; running twice is idempotent
printf '%s\n' "$KEY" > "$T/root.pub"
sh "$INST" --base-url "$B" --root-pub "$T/root.pub" --cli "$T/3pa.mjs" --cli-sha256 "$CS" --replace-root >/dev/null 2>&1 \
  && sh "$INST" --base-url "$B" --root-pub "$T/root.pub" --cli "$T/3pa.mjs" --cli-sha256 "$CS" >/dev/null 2>&1 && ok || bad "file key / idempotent"

# uninstall keeps the pinned key and the app home; --purge-state removes the state
mkdir -p "$HOME/.config/herdr-app"; echo x > "$HOME/.config/herdr-app/keep"
sh "$INST" --uninstall >/dev/null 2>&1
[ ! -e "$HOME/.local/bin/3pa" ] && [ ! -e "$HOME/.local/bin/herdr-fab" ] && [ ! -e "$HOME/.local/lib/3pa" ] && ok || bad "uninstall left files"
[ -f "$HOME/.config/3pa/workspace/root.pub" ] && [ -f "$HOME/.config/herdr-app/keep" ] && ok || bad "uninstall removed state or app home"
sh "$INST" --uninstall --purge-state >/dev/null 2>&1
[ ! -e "$HOME/.config/3pa/workspace" ] && [ -f "$HOME/.config/herdr-app/keep" ] && ok || bad "purge-state"

printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
