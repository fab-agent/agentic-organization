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
expect_fail "prefix reaches home via .." "must not contain" base --prefix "$HOME/sub/.."
expect_fail "state inside lib" "overlap" base --state-dir "$HOME/.local/lib/3pa/state"
expect_fail "app home equals state" "overlap" base --state-dir "$HOME/x" --app-home "$HOME/x"
expect_fail "backslash in path" "backslashes" base --prefix "$HOME/a\\b"
expect_fail "newline in path" "control characters" base --prefix "$HOME/a
b"
ln -s "$HOME" "$T/homelink"
expect_fail "symlink to home as state" "may not be" base --state-dir "$T/homelink"
mkdir -p "$HOME/foreign"; echo mine > "$HOME/foreign/f"
sh "$INST" --uninstall --purge-state --state-dir "$HOME/foreign" >/dev/null 2>&1
[ -f "$HOME/foreign/f" ] && [ -f "$HOME/personal.txt" ] && [ -f "$HOME/.config/herdr-app/keep" ] && ok || bad "purge removed foreign data"
# I10: a pre-existing folder with personal files is never emptied, even after an install into it
mkdir -p "$HOME/pre"; echo mine > "$HOME/pre/personal.txt"
base --state-dir "$HOME/pre" >/dev/null 2>&1 && sh "$INST" --uninstall --purge-state --state-dir "$HOME/pre" >/dev/null 2>&1
[ -f "$HOME/pre/personal.txt" ] && [ ! -e "$HOME/pre/root.pub" ] && ok || bad "purge took a foreign file or left the key"
rm -rf "$HOME/.local" "$HOME/.config/3pa"
base >/dev/null 2>&1 && sh "$INST" --uninstall --purge-state >/dev/null 2>&1 && [ ! -e "$HOME/.config/3pa/workspace" ] && [ -f "$HOME/personal.txt" ] && ok || bad "purge of our own state"
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

# ── Codex round 2 (I9-I12) ───────────────────────────────────────────────────
rm -rf "$HOME/.local" "$HOME/.config/3pa"
mkdir -p "$T/hop-target" "$HOME/.config/herdr-app"; ln -s "$T/hop-target" "$HOME/alias"
expect_fail "state with .." "must not contain \.\." base --state-dir "$HOME/alias/../home"
expect_fail "prefix with .." "must not contain \.\." base --prefix "$HOME/alias/../x"
expect_fail "uninstall with .." "must not contain \.\." sh "$INST" --uninstall --purge-state --state-dir "$HOME/alias/../home"
[ -f "$HOME/personal.txt" ] && ok || bad "personal file removed through .."
mkdir -p "$T/p1"; ln -s "$HOME/.config/herdr-app" "$T/p1/bin"
expect_fail "bin linked to app home" "overlap" base --prefix "$T/p1"
echo mine > "$HOME/.config/herdr-app/3pa"
expect_fail "uninstall: bin linked to app home" "overlap" sh "$INST" --uninstall --prefix "$T/p1"
[ -f "$HOME/.config/herdr-app/3pa" ] && ok || bad "uninstall removed a file through the bin link"
mkdir -p "$T/p2/lib"; ln -s "$HOME/.config/herdr-app" "$T/p2/lib/3pa"
expect_fail "lib linked to app home" "overlap" base --prefix "$T/p2"
[ ! -e "$HOME/.config/herdr-app/3pa.mjs" ] && ok || bad "install wrote through the lib link"
mkdir -p "$T/p3"; ln -s "$HOME" "$T/p3/bin"
expect_fail "bin linked to home" "may not be" base --prefix "$T/p3"
# I12: the URL is judged after the same normalisation the CLI applies
sh "$INST" --base-url "$(printf 'https://platform.example\t')" --root-pub "$KEY" --cli "$T/3pa.mjs" --cli-sha256 "$CS" --dry-run >/dev/null 2>&1 && ok || bad "tab-padded url"

# ── Codex round 3 (I13-I16) ──────────────────────────────────────────────────
rm -rf "$HOME/.local" "$HOME/.config/3pa" "$T/st13"
# I13: only exact names are ours
mkdir -p "$T/st13"
for n in personal.txt state.json.notes state.jsonl sync.locksmith sync.lock-notes .root.pub.notes root.pub.bak; do echo mine > "$T/st13/$n"; done
for n in root.pub state.json state.json.replaced-1730000000000 sync.lock sync.lock.takeover sync.lock.tmp-0123456789ab state.json.0123456789ab.tmp; do echo ours > "$T/st13/$n"; done
sh "$INST" --uninstall --purge-state --state-dir "$T/st13" >/dev/null 2>&1
[ "$(ls -A "$T/st13" | sort | tr '\n' ' ')" = ".root.pub.notes personal.txt root.pub.bak state.json.notes state.jsonl sync.lock-notes sync.locksmith " ] && ok || bad "purge grammar: $(ls -A "$T/st13" | tr '\n' ' ')"
rm -rf "$T/st13"
# I14: link/ and link/. are the same link
mkdir -p "$T/tgt14"; chmod 755 "$T/tgt14"; echo key > "$T/tgt14/root.pub"; ln -s "$T/tgt14" "$T/lnk14"
for s in "" "/" "/." "//" "/./"; do
  expect_fail "state link$s" "link or not a folder" base --state-dir "$T/lnk14$s"
  expect_fail "purge state link$s" "link or not a folder" sh "$INST" --uninstall --purge-state --state-dir "$T/lnk14$s"
done
[ "$(perm "$T/tgt14")" = "755" ] && [ -f "$T/tgt14/root.pub" ] && ok || bad "link target touched"
# I15: an unreadable state folder is an error, never success
mkdir -p "$T/st15"; echo k > "$T/st15/root.pub"; echo s > "$T/st15/state.json"; chmod 000 "$T/st15"
expect_fail "purge unreadable state" "nothing was removed" sh "$INST" --uninstall --purge-state --state-dir "$T/st15"
chmod 700 "$T/st15"; [ -f "$T/st15/root.pub" ] && [ -f "$T/st15/state.json" ] && ok || bad "unreadable purge"
# a root.pub that is a folder is left, and said so
rm -rf "$T/st15"; mkdir -p "$T/st15/root.pub"
out="$(sh "$INST" --uninstall --purge-state --state-dir "$T/st15" 2>&1)"
[ -d "$T/st15/root.pub" ] && printf %s "$out" | grep -q "not a regular file" && ok || bad "folder root.pub purge: $out"
# I16: a folder where a file is to be published stops the install before anything changes
for n in lib/3pa/3pa.mjs lib/3pa/herdr bin/3pa bin/herdr-fab; do
  rm -rf "$T/p16"; mkdir -p "$T/p16/$n"
  expect_fail "dest is a folder: $n" "not a plain file" base --herdr-bin "$T/herdr" --herdr-sha256 "$HS" --prefix "$T/p16" --state-dir "$T/p16s"
  [ ! -e "$T/p16s/root.pub" ] && [ -z "$(find "$T/p16" -name '*.tmp')" ] && ok || bad "changes after dest-folder refusal: $n"
done
rm -rf "$T/p16"; mkdir -p "$T/p16/bin"; ln -s "$T" "$T/p16/bin/3pa"
expect_fail "dest is a link" "not a plain file" base --prefix "$T/p16" --state-dir "$T/p16s"

# ── Codex round 4 (I17-I18) ──────────────────────────────────────────────────
NL='
'
rm -rf "$T/lf" "$HOME/.local"; mkdir -p "$T/lf/state" "$T/lf/other"; echo k > "$T/lf/state/root.pub"; echo s > "$T/lf/state/state.json"
expect_fail "state ends with newline (install)" "control characters" base --state-dir "$T/lf/state$NL"
expect_fail "state ends with newline (purge)" "control characters" sh "$INST" --uninstall --purge-state --state-dir "$T/lf/state$NL"
expect_fail "prefix ends with newline" "control characters" base --prefix "$T/lf/other$NL"
expect_fail "app home ends with newline" "control characters" base --app-home "$T/lf/other$NL"
expect_fail "state has a tab" "control characters" base --state-dir "$T/lf/a	b"
[ -f "$T/lf/state/root.pub" ] && [ -f "$T/lf/state/state.json" ] && [ ! -e "$T/lf/other/lib" ] && ok || bad "newline path reached another folder"
# I18: an empty lib folder that cannot be removed is reported as such
base --prefix "$T/lf/pfx" --state-dir "$T/lf/st2" >/dev/null 2>&1; chmod 555 "$T/lf/pfx/lib"
expect_fail "lib rmdir permission" "could not remove the empty folder" sh "$INST" --uninstall --prefix "$T/lf/pfx" --state-dir "$T/lf/st2"
chmod 755 "$T/lf/pfx/lib"

# ── Codex round 5 (I19-I20) ──────────────────────────────────────────────────
# I19: non-ASCII folder names are fine (only control characters and backslashes are not)
U="$T/Çağrı-東京"; mkdir -p "$U"
base --prefix "$U/p" --state-dir "$U/s" --app-home "$U/a" >/dev/null 2>&1 && [ -f "$U/s/root.pub" ] && ok || bad "unicode paths refused"
sh "$INST" --uninstall --purge-state --prefix "$U/p" --state-dir "$U/s" >/dev/null 2>&1 && [ ! -e "$U/s" ] && ok || bad "unicode uninstall"
# I20: a file named only by a newline keeps the folder with the right message; a link is kept, not an error
rm -rf "$T/i20"; base --prefix "$T/i20" --state-dir "$T/i20s" >/dev/null 2>&1
printf x > "$T/i20/lib/3pa/$NL"
out="$(sh "$INST" --uninstall --prefix "$T/i20" --state-dir "$T/i20s" 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf %s "$out" | grep -q "files that are not ours" && ok || bad "newline-named file in lib: rc=$rc $out"
rm -rf "$T/i20" "$T/i20t"; mkdir -p "$T/i20/lib" "$T/i20t"; ln -s "$T/i20t" "$T/i20/lib/3pa"
out="$(sh "$INST" --uninstall --prefix "$T/i20" --state-dir "$T/i20s" 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf %s "$out" | grep -q "a link" && [ -d "$T/i20t" ] && ok || bad "lib link: rc=$rc $out"

# ── Codex round 6 (I21) ──────────────────────────────────────────────────────
rm -rf "$T/i21"; mkdir -p "$T/i21/real"; echo B > "$T/i21/real/root.pub"; chmod 755 "$T/i21/real"
BAD="$(printf '%s/i21/state-\377' "$T")"
ln -s "$T/i21/real" "$BAD" 2>/dev/null
expect_fail "invalid UTF-8 state path" "valid UTF-8" base --state-dir "$BAD"
expect_fail "invalid UTF-8 purge path" "valid UTF-8" sh "$INST" --uninstall --purge-state --state-dir "$BAD"
[ "$(cat "$T/i21/real/root.pub")" = "B" ] && [ "$(perm "$T/i21/real")" = "755" ] && ok || bad "invalid UTF-8 path reached the pinned key"
# a real U+FFFD character is valid UTF-8 and is judged like any other name
U2="$T/i21/state-$(printf '\357\277\275')"; ln -s "$T/i21/real" "$U2"
expect_fail "U+FFFD state link" "link or not a folder" base --state-dir "$U2"

# ── Release chain options (ADR-0031) ─────────────────────────────────────────
rm -rf "$T/rc"; RK="$(node -e 'process.stdout.write(Buffer.alloc(32,3).toString("base64"))')"; RK2="$(node -e 'process.stdout.write(Buffer.alloc(32,4).toString("base64"))')"
RU="https://dl.example/release.json"
expect_fail "release key without url" "go together" base --prefix "$T/rc" --state-dir "$T/rcs" --release-pub "$RK"
expect_fail "release url without key" "go together" base --prefix "$T/rc" --state-dir "$T/rcs" --release-url "$RU"
expect_fail "release key short" "release-pub is not a valid" base --prefix "$T/rc" --state-dir "$T/rcs" --release-pub AAAA --release-url "$RU"
expect_fail "release url http remote" "release-url must be https" base --prefix "$T/rc" --state-dir "$T/rcs" --release-pub "$RK" --release-url http://dl.example/r.json
expect_fail "release url credentials" "release-url must be https" base --prefix "$T/rc" --state-dir "$T/rcs" --release-pub "$RK" --release-url https://u:p@dl.example/r.json
[ ! -e "$T/rcs" ] && ok || bad "state created before release options were refused"
base --prefix "$T/rc" --state-dir "$T/rcs" --release-pub "$RK" --release-url "$RU" >/dev/null 2>&1 && ok || bad "release install"
[ "$(cat "$T/rcs/release.pub")" = "$RK" ] && [ "$(cat "$T/rcs/release-url")" = "$RU" ] && ok || bad "release files"
[ "$(perm "$T/rcs/release.pub")" = "644" ] && ok || bad "release.pub mode"
expect_fail "release key swap" "different release key" base --prefix "$T/rc" --state-dir "$T/rcs" --release-pub "$RK2" --release-url "$RU"
[ "$(cat "$T/rcs/release.pub")" = "$RK" ] && ok || bad "release key replaced without flag"
base --prefix "$T/rc" --state-dir "$T/rcs" --release-pub "$RK2" --release-url "$RU" --replace-release-key >/dev/null 2>&1 && [ "$(cat "$T/rcs/release.pub")" = "$RK2" ] && ok || bad "explicit release key replacement"
# the release files and the update state go with --purge-state; nothing else does
echo mine > "$T/rcs/notes.txt"; echo '{}' > "$T/rcs/release-state.json"
sh "$INST" --uninstall --purge-state --prefix "$T/rc" --state-dir "$T/rcs" >/dev/null 2>&1
[ "$(ls -A "$T/rcs")" = "notes.txt" ] && ok || bad "purge of release files: $(ls -A "$T/rcs" | tr '\n' ' ')"
# an installed bundle can find the pinned key and URL it was given
rm -rf "$T/rc" "$T/rcs"; base --prefix "$T/rc" --state-dir "$T/rcs" --release-pub "$RK" --release-url "$RU" >/dev/null 2>&1
[ -f "$T/rcs/release.pub" ] && [ -f "$T/rcs/release-url" ] && ok || bad "release files after reinstall"

# R3: the release-url destination must be absent or a plain file
rm -rf "$T/r3" "$T/r3s"; mkdir -p "$T/r3s/release-url"
expect_fail "release-url is a folder" "not a plain file" base --prefix "$T/r3" --state-dir "$T/r3s" --release-pub "$RK" --release-url "$RU"
[ ! -e "$T/r3/lib/3pa/3pa.mjs" ] && [ -z "$(find "$T/r3s" -name '*.tmp')" ] && ok || bad "changes after release-url refusal"
rm -rf "$T/r3s"; mkdir -p "$T/r3s" "$T/r3t"; ln -s "$T/r3t" "$T/r3s/release-url"
expect_fail "release-url is a link" "not a plain file" base --prefix "$T/r3" --state-dir "$T/r3s" --release-pub "$RK" --release-url "$RU"

# the wrapper carries this install's own state/app locations (custom --state-dir must work with self-update)
rm -rf "$T/wr"; base --prefix "$T/wr" --state-dir "$T/wr s" --app-home "$T/it's app" >/dev/null 2>&1
WRAP="$T/wr/bin/3pa"
grep -q "THREEPA_WORKSPACE_DIR='$T/wr s'" "$WRAP" && grep -q "HERDR_APP_HOME='$T/it'\\\\''s app'" "$WRAP" && ok || bad "wrapper env: $(cat "$WRAP")"
printf 'console.log(process.env.THREEPA_WORKSPACE_DIR + "|" + process.env.HERDR_APP_HOME)\n' > "$T/wr/lib/3pa/3pa.mjs"
[ "$(PATH="$(dirname "$(command -v node)"):$PATH" "$WRAP")" = "$T/wr s|$T/it's app" ] && ok || bad "wrapper does not export the locations"
[ "$(THREEPA_WORKSPACE_DIR=/x PATH="$(dirname "$(command -v node)"):$PATH" "$WRAP" | cut -d'|' -f1)" = "/x" ] && ok || bad "explicit environment must win"

# ADR-0036: the wrapper knows the installed Herdr; the launcher starts the layout switch in the background
rm -rf "$T/ac"; base --prefix "$T/ac" --state-dir "$T/acs" --herdr-bin "$T/herdr" --herdr-sha256 "$HS" >/dev/null 2>&1
grep -q "THREEPA_HERDR_BIN='$T/ac/lib/3pa/herdr'" "$T/ac/bin/3pa" && ok || bad "wrapper does not name the Herdr binary"
grep -q 'workspace activate --wait 60 --quiet >/dev/null 2>&1 &' "$T/ac/bin/herdr-fab" && ok || bad "launcher does not start the layout switch"
rm -rf "$T/ac2"; base --prefix "$T/ac2" --state-dir "$T/ac2s" >/dev/null 2>&1
! grep -q THREEPA_HERDR_BIN "$T/ac2/bin/3pa" && ok || bad "wrapper names a Herdr that was not installed"

printf '%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
