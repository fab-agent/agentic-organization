// Tests for the deployment helper (ADR-0033). Run: node --test installers/deploy/deploy.test.mjs
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { parseConfig } from './deploy.mjs'

const WIN = process.platform === 'win32'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const T = mkdtempSync(path.join(tmpdir(), 'deploy-'))
const sha = (f) => createHash('sha256').update(readFileSync(f)).digest('hex')
const HOME = path.join(T, 'home'); mkdirSync(HOME, { recursive: true })
const ENV = { ...process.env, HOME, USERPROFILE: HOME, LOCALAPPDATA: path.join(HOME, 'AppData', 'Local'), APPDATA: path.join(HOME, 'AppData', 'Roaming') }
delete ENV.THREEPA_WORKSPACE_DIR
const KEY = Buffer.alloc(32, 7).toString('base64'), OTHER = Buffer.alloc(32, 9).toString('base64')
const RK = Buffer.alloc(32, 3).toString('base64')
const isRoot = !WIN && process.getuid?.() === 0

const cli = path.join(T, '3pa.mjs'); writeFileSync(cli, 'console.log("3pa-stub")\n')
const CLI_SHA = sha(cli)
const conf = (over = {}, name = 'deploy.conf') => {
  const c = { BASE_URL: 'https://platform.example', ROOT_PUB: KEY, RELEASE_PUB: RK, RELEASE_URL: 'https://dl.example/release.json', CLI_FILE: '3pa.mjs', CLI_SHA256: CLI_SHA, ...over }
  const f = path.join(T, name)
  writeFileSync(f, Object.entries(c).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${v}`).join('\n') + '\n')
  return f
}
const run = (args) => {
  const a = ['--allow-elevated']; // hosted Windows runners are elevated
  const r = spawnSync(process.execPath, [path.join(HERE, 'deploy.mjs'), ...args, ...(WIN ? a : [])], { encoding: 'utf8', env: ENV })
  return { rc: r.status, out: (r.stdout ?? '') + (r.stderr ?? '') }
}

test('settings file: only KEY=VALUE, known keys, no tricks', () => {
  const good = parseConfig(readFileSync(path.join(HERE, 'deploy.conf.example'), 'utf8').replace(/^HERDR_FILE=$/m, 'HERDR_FILE=').replace(/CLI_SHA256=0+/, 'CLI_SHA256=' + 'a'.repeat(64)))
  assert.equal(good.BASE_URL, 'https://platform.example.com')
  for (const [text, pat] of [
    ['FOO=1\n', /unknown setting/], ['BASE_URL\n', /KEY=VALUE/], ['BASE_URL=a\nBASE_URL=b\n', /twice/],
    ['BASE_URL=$(touch x)\n', /not allowed/], ['BASE_URL=`x`\n', /not allowed/], ['BASE_URL="x"\n', /not allowed/], ['BASE_URL=a\\b\n', /not allowed/],
    ['BASE_URL=x\n', /ROOT_PUB is required/],
  ]) assert.throws(() => parseConfig(text), pat, text)
  const base = `BASE_URL=https://x\nROOT_PUB=k\nCLI_FILE=f\n`
  assert.throws(() => parseConfig(base + 'CLI_SHA256=abc\n'), /64 lowercase/)
  assert.throws(() => parseConfig(base + `CLI_SHA256=${'a'.repeat(64)}\nHERDR_FILE=h\n`), /go together/)
  assert.throws(() => parseConfig(base + `CLI_SHA256=${'a'.repeat(64)}\nRELEASE_PUB=k\n`), /go together/)
  assert.deepEqual(Object.keys(parseConfig('# c\n\n' + base + `CLI_SHA256=${'a'.repeat(64)}\n`)).sort(), ['BASE_URL', 'CLI_FILE', 'CLI_SHA256', 'ROOT_PUB'])
})

test('check never changes anything; install is idempotent; drift in bundle or keys is reported', { skip: isRoot }, () => {
  const f = conf()
  let r = run(['check', '--config', f]); assert.equal(r.rc, 1); assert.match(r.out, /not installed/)
  assert.ok(!existsSync(path.join(HOME, '.local')) && !existsSync(path.join(HOME, 'AppData')), 'check wrote nothing')
  r = run(['install', '--config', f]); assert.equal(r.rc, 0, r.out)
  r = run(['check', '--config', f]); assert.equal(r.rc, 0, r.out); assert.match(r.out, /^compliant/)
  r = run(['install', '--config', f]); assert.equal(r.rc, 0); assert.match(r.out, /already installed as intended/)
  // a different root key, release key, release url or bundle hash is non-compliant
  for (const [over, pat] of [[{ ROOT_PUB: OTHER }, /root key/], [{ RELEASE_PUB: OTHER }, /release key/], [{ RELEASE_URL: 'https://dl.example/other.json' }, /release URL/]]) {
    r = run(['check', '--config', conf(over, 'drift.conf')]); assert.equal(r.rc, 1, JSON.stringify(over)); assert.match(r.out, pat)
  }
  const cli2 = path.join(T, 'cli2'); mkdirSync(cli2); writeFileSync(path.join(cli2, '3pa.mjs'), 'console.log("new")\n')
  r = run(['check', '--config', conf({ CLI_FILE: 'cli2/3pa.mjs', CLI_SHA256: sha(path.join(cli2, '3pa.mjs')) }, 'newer.conf')]); assert.equal(r.rc, 1); assert.match(r.out, /not the intended one/)
  // a different pinned key is NOT silently replaced by an install (that needs the installer's explicit flag)
  r = run(['install', '--config', conf({ ROOT_PUB: OTHER }, 'swap.conf')]); assert.notEqual(r.rc, 0); assert.match(r.out, /different root key/)
})

test('install refuses a wrong hash and a missing bundle, and says so', { skip: isRoot }, () => {
  const h = path.join(T, 'hhome'); mkdirSync(h, { recursive: true })
  const env = { ...ENV, HOME: h, USERPROFILE: h, LOCALAPPDATA: path.join(h, 'L'), APPDATA: path.join(h, 'A') }
  const go = (f) => spawnSync(process.execPath, [path.join(HERE, 'deploy.mjs'), 'install', '--config', f, ...(WIN ? ['--allow-elevated'] : [])], { encoding: 'utf8', env })
  let r = go(conf({ CLI_SHA256: '1'.repeat(64) }, 'wrong.conf')); assert.notEqual(r.status, 0); assert.match(r.stdout + r.stderr, /does not match/)
  r = go(conf({ CLI_FILE: 'missing.mjs' }, 'missing.conf')); assert.notEqual(r.status, 0); assert.match(r.stdout + r.stderr, /does not exist/)
  assert.ok(!existsSync(path.join(h, '.local', 'lib', '3pa', '3pa.mjs')))
})

test('deploy.sh: refuses to act for someone else, and root needs a named user', { skip: WIN }, () => {
  const f = conf(); const sh = path.join(HERE, 'deploy.sh')
  const go = (...a) => spawnSync('sh', [sh, ...a], { encoding: 'utf8', env: ENV })
  let r = go('check'); assert.equal(r.status, 2)
  r = go('check', '--config', path.join(T, 'nope')); assert.equal(r.status, 2)
  r = go('check', '--config', f, '--bogus'); assert.equal(r.status, 2)
  if (isRoot) {
    r = go('check', '--config', f); assert.equal(r.status, 2); assert.match(r.stdout + r.stderr, /--user/)
    r = go('check', '--config', f, '--user', 'root'); assert.equal(r.status, 3)
    r = go('check', '--config', f, '--user', 'x;touch INJECTED'); assert.equal(r.status, 2); assert.match(r.stdout + r.stderr, /unusual user name/)
    r = go('check', '--config', f, '--user', 'no-such-user-xyz'); assert.equal(r.status, 2)
  } else {
    r = go('check', '--config', f, '--user', 'someone-else'); assert.equal(r.status, 3); assert.match(r.stdout + r.stderr, /cannot act for/)
    const fresh = path.join(T, 'fresh'); mkdirSync(fresh)
    r = spawnSync('sh', [sh, 'check', '--config', f], { encoding: 'utf8', env: { ...ENV, HOME: fresh, USERPROFILE: fresh, LOCALAPPDATA: path.join(fresh, 'L') } })
    assert.equal(r.status, 1) // not installed yet: a real answer, not an error
  }
})
