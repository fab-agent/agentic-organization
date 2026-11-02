// Tests for the deployment helper (ADR-0033). Run: node --test installers/deploy/deploy.test.mjs
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
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
  assert.equal(good.BASE_URL, 'https://platform.example.com/') // the installer's normal form
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
  r = run(['check', '--config', conf({ CLI_FILE: 'cli2/3pa.mjs', CLI_SHA256: sha(path.join(cli2, '3pa.mjs')) }, 'newer.conf')]); assert.equal(r.rc, 1); assert.match(r.out, /not the one in the settings/)
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

// ═══ Codex round 1 (D1-D7) ═══════════════════════════════════════════════════
const fresh = (name) => { const h = path.join(T, name); mkdirSync(h, { recursive: true }); return { HOME: h, USERPROFILE: h, LOCALAPPDATA: path.join(h, 'L'), APPDATA: path.join(h, 'A') } }
const runIn = (env, args) => { const r = spawnSync(process.execPath, [path.join(HERE, 'deploy.mjs'), ...args, ...(WIN ? ['--allow-elevated'] : [])], { encoding: 'utf8', env: { ...ENV, ...env } }); return { rc: r.status, out: (r.stdout ?? '') + (r.stderr ?? '') } }
const stateOf = (h) => (WIN ? path.join(h.LOCALAPPDATA, '3pa', 'workspace') : path.join(h.HOME, '.config', '3pa', 'workspace'))
const bundleOf = (h) => (WIN ? path.join(h.LOCALAPPDATA, '3pa', 'lib', '3pa', '3pa.mjs') : path.join(h.HOME, '.local', 'lib', '3pa', '3pa.mjs'))
const libOf = (h) => path.dirname(bundleOf(h))

test('D1: a custom THREEPA_WORKSPACE_DIR is honoured by install AND check', { skip: isRoot }, () => {
  const h = fresh('d1'); const custom = path.join(T, 'd1-custom-state'); const env = { ...h, THREEPA_WORKSPACE_DIR: custom }
  const f = conf({}, 'd1.conf')
  assert.equal(runIn(env, ['install', '--config', f]).rc, 0)
  assert.ok(existsSync(path.join(custom, 'root.pub')), 'pinned where it was asked to be')
  assert.ok(!existsSync(stateOf(h)), 'no second trust state in the default place')
  assert.equal(runIn(env, ['check', '--config', f]).rc, 0)
})

test('D2/D8: a file that differs from the settings is never overwritten by install (no guessing about why); --force-artifacts is the explicit way', { skip: isRoot }, () => {
  const h = fresh('d2'); const f = conf({}, 'd2.conf')
  assert.equal(runIn(h, ['install', '--config', f]).rc, 0)
  writeFileSync(bundleOf(h), 'console.log("NEWER signed bundle")\n') // what self-update leaves behind (or a tamperer)
  // whatever sits in release-state.json (nothing, garbage, a folder) changes nothing about the decision
  for (const make of [() => {}, () => writeFileSync(path.join(stateOf(h), 'release-state.json'), ''), () => { rmSync(path.join(stateOf(h), 'release-state.json'), { force: true }); mkdirSync(path.join(stateOf(h), 'release-state.json')) }]) {
    make()
    let r = runIn(h, ['check', '--config', f]); assert.equal(r.rc, 1, r.out); assert.match(r.out, /3pa bundle is not the one in the settings/)
    r = runIn(h, ['install', '--config', f]); assert.equal(r.rc, 0, r.out); assert.match(r.out, /kept .* \(it differs from the settings/)
    assert.match(readFileSync(bundleOf(h), 'utf8'), /NEWER signed bundle/, 'not rolled back')
  }
  // --pins-only ignores the files, not the trust setup
  assert.equal(runIn(h, ['check', '--config', f, '--pins-only']).rc, 0)
  assert.equal(runIn(h, ['check', '--config', conf({ ROOT_PUB: OTHER }, 'd2-other.conf'), '--pins-only']).rc, 1)
  // the explicit way back
  const r = runIn(h, ['install', '--config', f, '--force-artifacts']); assert.equal(r.rc, 0, r.out)
  assert.equal(sha(bundleOf(h)), CLI_SHA); assert.equal(runIn(h, ['check', '--config', f]).rc, 0)
})

test('D9: a MISSING file is installed from the settings (the bootstrap version); a present newer one beside it is kept', { skip: isRoot }, () => {
  const h = fresh('d9'); const herdr = path.join(T, WIN ? 'herdr.exe' : 'herdr'); copyFileSync(process.execPath, herdr)
  const f = conf({ HERDR_FILE: path.basename(herdr), HERDR_SHA256: sha(herdr) }, 'd9.conf')
  assert.equal(runIn(h, ['install', '--config', f]).rc, 0)
  writeFileSync(bundleOf(h), 'console.log("NEWER signed bundle")\n')
  rmSync(path.join(libOf(h), WIN ? 'herdr.exe' : 'herdr'))
  const r = runIn(h, ['install', '--config', f]); assert.equal(r.rc, 0, r.out)
  assert.ok(existsSync(path.join(libOf(h), WIN ? 'herdr.exe' : 'herdr')), 'the missing binary came back')
  assert.match(readFileSync(bundleOf(h), 'utf8'), /NEWER signed bundle/, 'the newer bundle was kept')
})

test('D10: a missing or damaged entry script is non-compliant and is repaired', { skip: isRoot }, () => {
  const h = fresh('d10'); const herdr = path.join(T, WIN ? 'herdr.exe' : 'herdr'); copyFileSync(process.execPath, herdr)
  const f = conf({ HERDR_FILE: path.basename(herdr), HERDR_SHA256: sha(herdr) }, 'd10.conf')
  assert.equal(runIn(h, ['install', '--config', f]).rc, 0); assert.equal(runIn(h, ['check', '--config', f]).rc, 0)
  const bin = path.dirname(WIN ? path.join(h.LOCALAPPDATA, '3pa', 'bin', 'x') : path.join(h.HOME, '.local', 'bin', 'x'))
  const wrapper = path.join(bin, WIN ? '3pa.cmd' : '3pa'), launcher = path.join(bin, WIN ? 'herdr-fab.cmd' : 'herdr-fab')
  rmSync(wrapper)
  let r = runIn(h, ['check', '--config', f]); assert.equal(r.rc, 1); assert.match(r.out, /3pa entry script/)
  assert.equal(runIn(h, ['install', '--config', f]).rc, 0); assert.ok(existsSync(wrapper))
  writeFileSync(launcher, '')
  r = runIn(h, ['check', '--config', f]); assert.equal(r.rc, 1); assert.match(r.out, /launcher/)
  writeFileSync(launcher, readFileSync(launcher, 'utf8') + 'echo extra\n')
  assert.equal(runIn(h, ['check', '--config', f]).rc, 1)
  assert.equal(runIn(h, ['install', '--config', f]).rc, 0); assert.equal(runIn(h, ['check', '--config', f]).rc, 0)
})

test('D3: the release URL is compared in the installer\'s own normal form', { skip: isRoot }, () => {
  const h = fresh('d3')
  for (const [i, url] of ['HTTPS://dl.example', 'https://dl.example/a/b?x=1', 'http://localhost:8080/r.json', 'https://DL.example:443/r.json'].entries()) {
    const f = conf({ RELEASE_URL: url }, `d3-${i}.conf`)
    assert.equal(runIn(h, ['install', '--config', f]).rc, 0, url)
    const r = runIn(h, ['check', '--config', f]); assert.equal(r.rc, 0, `${url}: ${r.out}`)
    assert.match(runIn(h, ['install', '--config', f]).out, /already installed as intended/, url)
  }
  for (const bad of ['http://dl.example/r', 'https://u:p@dl.example/r', 'https://dl.example/r#x', 'nonsense'])
    assert.equal(runIn(h, ['check', '--config', conf({ RELEASE_URL: bad }, 'd3-bad.conf')]).rc, 2, bad)
})

test('D4: a Herdr binary added to the settings later is installed (and detected), not skipped', { skip: isRoot }, () => {
  const h = fresh('d4'); assert.equal(runIn(h, ['install', '--config', conf({}, 'd4a.conf')]).rc, 0)
  const herdr = path.join(T, WIN ? 'herdr.exe' : 'herdr'); copyFileSync(process.execPath, herdr)
  const f = conf({ HERDR_FILE: path.basename(herdr), HERDR_SHA256: sha(herdr) }, 'd4b.conf')
  assert.equal(runIn(h, ['check', '--config', f]).rc, 1)
  const r = runIn(h, ['install', '--config', f]); assert.equal(r.rc, 0, r.out); assert.doesNotMatch(r.out, /already installed/)
  assert.ok(existsSync(path.join(libOf(h), WIN ? 'herdr.exe' : 'herdr')))
  assert.equal(runIn(h, ['check', '--config', f]).rc, 0)
  assert.equal(runIn(h, ['check', '--config', conf({ HERDR_FILE: path.basename(herdr), HERDR_SHA256: 'f'.repeat(64) }, 'd4c.conf')]).rc, 1)
})

test('D7: a malformed key in the settings is a configuration error, never "compliant"', { skip: isRoot }, () => {
  const h = fresh('d7'); mkdirSync(stateOf(h), { recursive: true }); writeFileSync(path.join(stateOf(h), 'root.pub'), 'not-a-key\n')
  const f = conf({ ROOT_PUB: 'not-a-key', RELEASE_PUB: undefined, RELEASE_URL: undefined }, 'd7.conf')
  const r = runIn(h, ['check', '--config', f]); assert.equal(r.rc, 2); assert.match(r.out, /not a valid Ed25519 public key/)
  assert.equal(runIn(h, ['install', '--config', f]).rc, 2)
})

test('settings: limits and the config path', () => {
  assert.throws(() => parseConfig('BASE_URL=https://x\n'.repeat(1) + 'ROOT_PUB=' + 'a'.repeat(5000) + '\n'), /too long/)
  assert.throws(() => parseConfig('#'.repeat(70 * 1024)), /too large/)
  const r = runIn({}, ['check', '--config', path.join(T, 'x\ny.conf')]); assert.equal(r.rc, 2); assert.match(r.out, /control characters/)
})

test('D5/D6: deploy.sh passes the config path untouched and keeps a home directory with spaces', { skip: WIN }, () => {
  const sh = path.join(HERE, 'deploy.sh')
  // D5: a path ending in a newline is a different file; deploy.sh must not quietly use the other one
  const a = conf({}, 'settings'); writeFileSync(path.join(T, 'settings\n'), 'garbage\n')
  if (!isRoot) { // (as root the user rule answers first; D6 below covers that branch)
    const r = spawnSync('sh', [sh, 'check', '--config', path.join(T, 'settings\n')], { encoding: 'utf8', env: ENV })
    assert.equal(r.status, 2, r.stdout + r.stderr); assert.match(r.stdout + r.stderr, /control characters/)
  }
  // D11: the helper next to deploy.sh is found even when the script's folder name ends in a newline
  const wrong = path.join(T, 'scripts'); const lf = path.join(T, 'scripts\n'); mkdirSync(wrong, { recursive: true }); mkdirSync(lf, { recursive: true })
  writeFileSync(path.join(wrong, 'deploy.mjs'), 'console.log("WRONG-SIBLING-HELPER")\n')
  copyFileSync(sh, path.join(lf, 'deploy.sh')); writeFileSync(path.join(lf, 'deploy.mjs'), 'console.log("RIGHT-HELPER")\n')
  if (!isRoot) {
    const o2 = spawnSync('sh', [path.join(lf, 'deploy.sh'), 'check', '--config', a], { encoding: 'utf8', env: ENV })
    assert.doesNotMatch(o2.stdout, /WRONG-SIBLING-HELPER/, o2.stdout + o2.stderr)
    assert.match(o2.stdout, /RIGHT-HELPER/, o2.stdout + o2.stderr)
  }
  // D6: a macOS-style home with a space, with every system tool replaced by a recording shim
  const shim = path.join(T, 'shims'); mkdirSync(shim, { recursive: true })
  const mk = (n, body) => { writeFileSync(path.join(shim, n), `#!/bin/sh\n${body}\n`); chmodSync(path.join(shim, n), 0o755) }
  const uhome = path.join(T, 'User Home'); mkdirSync(uhome, { recursive: true }); mkdirSync(path.join(T, 'User'), { recursive: true })
  mk('uname', 'echo Darwin'); mk('id', 'case "$1" in -u) echo 0;; *) exit 0;; esac')
  mk('stat', 'echo alice'); mk('dscl', `echo "NFSHomeDirectory: ${uhome}"`)
  mk('runuser', 'echo "RUNUSER $*"'); mk('node', 'echo node')
  const o = spawnSync('/bin/sh', [sh, 'check', '--config', a], { encoding: 'utf8', env: { PATH: `${shim}:/usr/bin:/bin`, HOME: T } })
  assert.match(o.stdout, new RegExp(`HOME=${uhome.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} `), o.stdout + o.stderr)
  assert.match(o.stdout, /runuser -u alice|RUNUSER -u alice/)
})
