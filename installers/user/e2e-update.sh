#!/bin/sh
# End to end (ADR-0031): install a first bundle with the installer, publish a signed release
# from a local server, and let the INSTALLED `3pa self-update` replace itself.
# Usage: sh e2e-update.sh   (run from anywhere; needs a built bundle: npm run bundle in packages/cli)
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"; CLI_DIR="$HERE/../../packages/cli"
BUNDLE="$CLI_DIR/dist/3pa.mjs"; [ -f "$BUNDLE" ] || { echo "build the bundle first (npm run bundle)"; exit 1; }
T="$(mktemp -d)"; SRV=""
# only a real, positive server pid is ever signalled (kill 0 would hit the whole process group)
cleanup() { if [ -n "$SRV" ] && [ "$SRV" -gt 0 ] 2>/dev/null; then kill "$SRV" 2>/dev/null || true; fi; rm -rf "$T"; }
trap cleanup EXIT
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
export HOME="$T/home"; mkdir -p "$HOME" "$T/srv"

# the "new release" is the same bundle with one extra line, so it is a different file
cp "$BUNDLE" "$T/srv/3pa"; printf '\n// release 2\n' >> "$T/srv/3pa"
NEWSHA="$(sha "$T/srv/3pa")"; NEWSIZE="$(wc -c < "$T/srv/3pa" | tr -d ' ')"
case "$(uname -s)" in Linux) OS=linux ;; *) OS=macos ;; esac
case "$(uname -m)" in x86_64|amd64) ARCH=x64 ;; *) ARCH=arm64 ;; esac

# a tiny static server on a free loopback port
cat > "$T/serve.mjs" <<'JS'
import { createServer } from 'node:http'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
const dir = process.argv[2]
const s = createServer((q, r) => { try { r.end(readFileSync(join(dir, q.url.slice(1)))) } catch { r.writeHead(404); r.end() } })
s.listen(0, '127.0.0.1', () => writeFileSync(join(dir, '.port'), String(s.address().port)))
JS
node "$T/serve.mjs" "$T/srv" & SRV=$!
i=0; while [ ! -f "$T/srv/.port" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done
PORT="$(cat "$T/srv/.port")"

# keys and the signed document
cd "$CLI_DIR"
KEYOUT="$(npx tsx scripts/release-sign.ts keygen --out "$T/keys")"
PUB="$(cat "$T/keys/release.pub")"
NOW="$(date +%s)"
cat > "$T/body.json" <<JSON
{"typ":"3pa-release","v":1,"channel":"stable","version":"9.9.9","seq":1,"issued_at":$((NOW-10)),"expires_at":$((NOW+3600)),
 "artifacts":[{"name":"3pa","os":"$OS","arch":"$ARCH","url":"http://127.0.0.1:$PORT/3pa","size":$NEWSIZE,"sha256":"$NEWSHA"}]}
JSON
npx tsx scripts/release-sign.ts sign --key "$T/keys/release.key" --body "$T/body.json" --out "$T/srv/release.json" >/dev/null

# install the OLD bundle, pinned to the release key and URL (the installer refuses root: fine in CI)
OLDSHA="$(sha "$BUNDLE")"
sh "$HERE/install.sh" --base-url https://platform.example --root-pub "$(node -e 'process.stdout.write(Buffer.alloc(32,7).toString("base64"))')" \
  --cli "$BUNDLE" --cli-sha256 "$OLDSHA" --release-pub "$PUB" --release-url "http://127.0.0.1:$PORT/release.json" >/dev/null
INST="$HOME/.local/lib/3pa/3pa.mjs"
[ "$(sha "$INST")" = "$OLDSHA" ] || { echo "FAIL: old bundle not installed"; exit 1; }

"$HOME/.local/bin/3pa" self-update --check 2>&1 | grep -q "Update available: 9.9.9" || { echo "FAIL: --check"; exit 1; }
[ "$(sha "$INST")" = "$OLDSHA" ] || { echo "FAIL: --check changed the bundle"; exit 1; }
"$HOME/.local/bin/3pa" self-update 2>&1 | grep -q "Updated to 9.9.9" || { echo "FAIL: update"; exit 1; }
[ "$(sha "$INST")" = "$NEWSHA" ] || { echo "FAIL: bundle was not replaced"; exit 1; }
"$HOME/.local/bin/3pa" self-update 2>&1 | grep -q "Already up to date" || { echo "FAIL: second run"; exit 1; }
"$HOME/.local/bin/3pa" workspace status >/dev/null 2>&1 || { echo "FAIL: updated bundle does not run"; exit 1; }

# a document signed by a different key is refused and changes nothing
"$CLI_DIR/node_modules/.bin/tsx" scripts/release-sign.ts keygen --out "$T/keys2" >/dev/null
sed 's/"seq":1/"seq":2/' "$T/body.json" > "$T/body2.json"
npx tsx scripts/release-sign.ts sign --key "$T/keys2/release.key" --body "$T/body2.json" --out "$T/srv/release.json" >/dev/null
"$HOME/.local/bin/3pa" self-update 2>&1 | grep -q "different key" || { echo "FAIL: wrong key accepted"; exit 1; }
[ "$(sha "$INST")" = "$NEWSHA" ] || { echo "FAIL: bundle changed after a refused release"; exit 1; }
echo "e2e update: ok"
