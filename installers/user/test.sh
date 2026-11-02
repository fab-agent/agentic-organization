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
    setpriv --reuid=65534 --regid=65534 --clear-groups env HOME=/nonexistent PATH="$D/bin:/usr/bin:/bin" sh "$D/test.sh"
  else
    su -s /bin/sh nobody -c "PATH=$D/bin:/usr/bin:/bin sh $D/test.sh"
  fi
  rc=$?; rm -rf "$D"; exit $rc
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

# ── Codex round 1 (I1-I8) ────────────────────────────────────────────────────
rm -rf "$HOME/.local" "$HOME/.config"
mkdir -p "$HOME/.config/herdr-app"; echo mine > "$HOME/.config/herdr-app/keep"; echo mine > "$HOME/personal.txt"
# I1: dangerous locations are refused, and purge never removes what is not ours
expect_fail "prefix is /" "may not be" base --prefix /
expect_fail "state is home" "may not be" base --state-dir "$HOME"
expect_fail "state is a parent of home" "may not be" base --state-dir "$(dirname "$HOME")"
expect_fail "prefix reaches home via .." "may not be" base --prefix "$HOME/sub/.."
expect_fail "state inside lib" "overlap" base --state-dir "$HOME/.local/lib/3pa/state"
expect_fail "app home equals state" "overlap" base --state-dir "$HOME/x" --app-home "$HOME/x"
expect_fail "backslash in path" "control characters or backslashes" base --prefix "$HOME/a\\b"
expect_fail "newline in path" "control characters" base --prefix "$HOME/a
b"
ln -s "$HOME" "$T/homelink"
expect_fail "symlink to home as state" "may not be" base --state-dir "$T/homelink"
mkdir -p "$HOME/foreign"; echo mine > "$HOME/foreign/f"
expect_fail "purge without marker" "not created by this installer" sh "$INST" --uninstall --purge-state --state-dir "$HOME/foreign"
[ -f "$HOME/foreign/f" ] && [ -f "$HOME/personal.txt" ] && [ -f "$HOME/.config/herdr-app/keep" ] && ok || bad "purge removed foreign data"
base >/dev/null 2>&1 && sh "$INST" --uninstall --purge-state >/dev/null 2>&1 && [ ! -e "$HOME/.config/3pa/workspace" ] && [ -f "$HOME/personal.txt" ] && ok || bad "marked purge"
# a foreign file inside our lib folder survives uninstall
base >/dev/null 2>&1; echo mine > "$HOME/.local/lib/3pa/other"; sh "$INST" --uninstall >/dev/null 2>&1
[ -f "$HOME/.local/lib/3pa/other" ] && [ ! -e "$HOME/.local/lib/3pa/3pa.mjs" ] && ok || bad "uninstall must remove only its own files"
rm -rf "$HOME/.local"

# I2: an unreadable state folder stops the install, never "no key yet"
base >/dev/null 2>&1; chmod 000 "$HOME/.config/3pa/workspace"
expect_fail "unreadable pinned key" "nothing was changed" sh "$INST" --base-url "$B" --root-pub "$OTHER" --cli "$T/3pa.mjs" --cli-sha256 "$CS"
chmod 700 "$HOME/.config/3pa/workspace"
[ "$(cat "$HOME/.config/3pa/workspace/root.pub")" = "$KEY" ] && ok || bad "key was replaced under an unreadable folder"
# I3: --uninstall --dry-run removes nothing and is refused
expect_fail "uninstall dry-run" "installing only" sh "$INST" --uninstall --dry-run
[ -x "$HOME/.local/bin/3pa" ] && ok || bad "dry-run uninstall removed files"
# I4: a state symlink is refused BEFORE its target is touched
rm -rf "$HOME/.config/3pa" "$HOME/.local"; mkdir -p "$T/target" "$HOME/.config/3pa"; chmod 755 "$T/target"; ln -s "$T/target" "$HOME/.config/3pa/workspace"
expect_fail "state symlink" "link or not a folder" base
[ "$(perm "$T/target")" = "755" ] && ok || bad "symlink target mode was changed"
# I5: root.pub being a folder is refused, nothing written inside it
rm -f "$HOME/.config/3pa/workspace"; mkdir -p "$HOME/.config/3pa/workspace/root.pub"
expect_fail "root.pub is a folder" "not a regular file" base
[ -z "$(ls -A "$HOME/.config/3pa/workspace/root.pub")" ] && ok || bad "temp moved into root.pub folder"
rm -rf "$HOME/.config/3pa" "$HOME/.local"
# I6: a failed copy leaves no temp file, and a wrong Herdr hash leaves the CLI and key uninstalled too
expect_fail "wrong herdr hash" "does not match" base --herdr-bin "$T/herdr" --herdr-sha256 "$(printf 1%.0s $(seq 64))"
[ ! -e "$HOME/.local/lib/3pa/3pa.mjs" ] && [ ! -e "$HOME/.config/3pa/workspace/root.pub" ] && [ ! -e "$HOME/.local/bin/3pa" ] && ok || bad "partial install after herdr hash mismatch"
[ -z "$(ls -A "$HOME/.local/lib/3pa" 2>/dev/null)" ] && ok || bad "temp files left after hash mismatch"
# I7: the hash does not depend on the folder name; a path ending in a newline is refused
base --prefix "$T/we\\ird" >/dev/null 2>&1 && bad "backslash prefix accepted" || ok
# I8: URL rule matches the CLI on parsed values
for u in "HTTPS://platform.example" "http://127.1:8000" "http://2130706433:8000" "http://[0:0:0:0:0:0:0:1]:8000" "http://localhost:8080/path/"; do
  sh "$INST" --base-url "$u" --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$CS" --dry-run >/dev/null 2>&1 && ok || bad "url accepted by CLI but not installer: $u"
done
for u in "http://platform.example" "http://localhost.evil.example" "https://u@platform.example" "ftp://x" "https://p.example/#f"; do
  sh "$INST" --base-url "$u" --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$CS" --dry-run >/dev/null 2>&1 && bad "url wrongly accepted: $u" || ok
done

printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
