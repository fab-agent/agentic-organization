// Tests for install.mjs (ADR-0032). Run: node --test installers/user/windows/install.test.mjs
// On Linux/macOS as root the installer refuses to run, so the child is started as `nobody`.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { chmodSync, chownSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const WIN = process.platform === 'win32'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const T = mkdtempSync(path.join(tmpdir(), 'wininst-'))
chmodSync(T, 0o777)
const sha = (f) => createHash('sha256').update(readFileSync(f)).digest('hex')
const asRoot = !WIN && process.getuid?.() === 0
const nodeBin = (() => { if (!asRoot) return process.execPath; const d = path.join(T, 'bin'); mkdirSync(d); chmodSync(d, 0o755); copyFileSync(process.execPath, path.join(d, 'node')); chmodSync(path.join(d, 'node'), 0o755); return path.join(d, 'node') })()
const INST = (() => { if (!asRoot) return path.join(HERE, 'install.mjs'); const f = path.join(T, 'install.mjs'); copyFileSync(path.join(HERE, 'install.mjs'), f); chmodSync(f, 0o644); return f })()

// as root the installer is started as `nobody`, and it (rightly) distrusts folders owned by root
const mk = (p) => { mkdirSync(p, { recursive: true }); if (asRoot) for (let d = p; d.length > T.length; d = path.dirname(d)) chownSync(d, 65534, 65534) }
const put = (p, text) => { writeFileSync(p, text); if (asRoot) chownSync(p, 65534, 65534) }
const HOME = path.join(T, 'home'); mkdirSync(HOME, { recursive: true }); chmodSync(HOME, 0o777)
const ENV = { ...process.env, HOME, USERPROFILE: HOME, LOCALAPPDATA: path.join(HOME, 'AppData', 'Local'), APPDATA: path.join(HOME, 'AppData', 'Roaming') }
function run(args, extra = {}) {
  const cmd = asRoot ? 'setpriv' : nodeBin
  const argv = asRoot ? ['--reuid=65534', '--regid=65534', '--clear-groups', nodeBin, INST, ...args] : [INST, ...args]
  if (WIN) argv.push('--allow-elevated') // hosted Windows runners are elevated; a test below checks the refusal
  const r = spawnSync(cmd, argv, { encoding: 'utf8', env: { ...ENV, ...extra } })
  return { rc: r.status, out: (r.stdout ?? '') + (r.stderr ?? '') }
}

const CLI = path.join(T, '3pa.mjs'); writeFileSync(CLI, 'console.log("3pa-stub", process.argv.slice(2).join(" "))\n')
const HERDR_SRC = WIN ? process.execPath : nodeBin // a real executable that takes -e
const HERDR = path.join(T, WIN ? 'herdr.exe' : 'herdr'); copyFileSync(HERDR_SRC, HERDR)
const KEY = Buffer.alloc(32, 7).toString('base64'), OTHER = Buffer.alloc(32, 9).toString('base64')
const RK = Buffer.alloc(32, 3).toString('base64'), RK2 = Buffer.alloc(32, 4).toString('base64')
const B = 'https://platform.example'
let n = 0
const loc = () => { const d = path.join(T, `case${++n}`); mkdirSync(d, { recursive: true }); chmodSync(d, 0o777); return { prefix: path.join(d, 'p'), state: path.join(d, 's'), app: path.join(d, 'a'), d } }
const base = (l, more = []) => ['--base-url', B, '--root-pub', KEY, '--cli', CLI, '--cli-sha256', sha(CLI), '--prefix', l.prefix, '--state-dir', l.state, '--app-home', l.app, ...more]
const withHerdr = ['--herdr-bin', HERDR, '--herdr-sha256', sha(HERDR)]
const ok = (r, m) => assert.equal(r.rc, 0, `${m ?? ''} ${r.out}`)
const refused = (r, pat, m) => { assert.notEqual(r.rc, 0, `${m ?? ''} should have been refused: ${r.out}`); assert.match(r.out, pat, m) }
const BIN = (l) => path.join(l.prefix, 'bin'), LIB = (l) => path.join(l.prefix, 'lib', '3pa')
const W3PA = (l) => path.join(BIN(l), WIN ? '3pa.cmd' : '3pa'), LAUNCH = (l) => path.join(BIN(l), WIN ? 'herdr-fab.cmd' : 'herdr-fab')

test('refusals: url, keys, hashes, options, links, relative and unsafe paths', () => {
  const l = loc()
  for (const [args, pat, m] of [
    [[], /--base-url is required/, 'no args'],
    [['--base-url', 'http://platform.example', '--root-pub', KEY, '--cli', CLI, '--cli-sha256', sha(CLI)], /must be https/, 'http remote'],
    [['--base-url', 'http://localhost.evil.example', '--root-pub', KEY, '--cli', CLI, '--cli-sha256', sha(CLI)], /must be https/, 'lookalike'],
    [['--base-url', 'https://u:p@platform.example', '--root-pub', KEY, '--cli', CLI, '--cli-sha256', sha(CLI)], /valid platform URL/, 'credentials'],
    [['--base-url', B, '--root-pub', 'AAAA', '--cli', CLI, '--cli-sha256', sha(CLI)], /Ed25519/, 'short key'],
    [['--base-url', B, '--root-pub', KEY.replace(/=$/, ''), '--cli', CLI, '--cli-sha256', sha(CLI)], /Ed25519/, 'non-canonical key'],
    [['--base-url', B, '--root-pub', KEY, '--cli', CLI, '--cli-sha256', 'abc'], /64 lowercase/, 'bad hash'],
    [['--nope'], /unknown option/, 'unknown option'],
  ]) refused(run(args), pat, m)
  refused(run(base(l, ['--herdr-bin', HERDR])), /go together/, 'herdr without hash')
  refused(run(base(l, ['--release-pub', RK])), /go together/, 'release key without url')
  refused(run(base(l, ['--release-pub', 'AAAA', '--release-url', 'https://dl.example/r.json'])), /release-pub is not a valid/)
  refused(run(base(l, ['--release-pub', RK, '--release-url', 'http://dl.example/r.json'])), /release-url must be https/)
  refused(run(base(l, ['--cli', path.join(T, 'missing')]).concat([])), /regular file|cannot inspect/, 'missing source')
  const link = path.join(T, 'link.mjs'); try { symlinkSync(CLI, link) } catch { /* no symlink right on this machine */ }
  if (existsSync(link)) refused(run(base(l).map((x) => (x === CLI ? link : x))), /regular file/, 'symlink source')
  refused(run(base(l).map((x) => (x === l.prefix ? 'relative/prefix' : x))), /absolute/, 'relative prefix')
  refused(run(base(l).map((x) => (x === l.prefix ? l.prefix + path.sep + '..' + path.sep + 'x' : x))), /must not contain \.\./, '..')
  refused(run(base(l).map((x) => (x === l.prefix ? l.prefix + '\n' : x))), /control characters/, 'trailing newline')
  refused(run(base(l).map((x) => (x === l.prefix ? l.prefix + '\t' : x))), /control characters/, 'tab')
  assert.ok(!existsSync(l.prefix) && !existsSync(l.state), 'nothing was created by any refusal')
  refused(run(base(l).map((x) => (x === l.state ? HOME : x))), /may not be/, 'state is home')
  refused(run(base(l).map((x) => (x === l.state ? path.dirname(HOME) : x))), /may not be/, 'state is a parent of home')
  refused(run(base(l).map((x) => (x === l.app ? l.state : x))), /overlap/, 'app home equals state')
  refused(run(base(l).map((x) => (x === l.state ? path.join(LIB(l), 'st') : x))), /overlap/, 'state inside lib')
})

test('wrong hash installs nothing (a wrong Herdr hash holds back the CLI and the key too)', () => {
  const l = loc()
  refused(run(base(l).map((x) => (x === sha(CLI) ? '0'.repeat(64) : x))), /does not match/)
  assert.ok(!existsSync(path.join(LIB(l), '3pa.mjs')) && !(existsSync(LIB(l)) && readdirSync(LIB(l)).length))
  refused(run(base(l, ['--herdr-bin', HERDR, '--herdr-sha256', '1'.repeat(64)])), /does not match/)
  assert.ok(!existsSync(path.join(LIB(l), '3pa.mjs')) && !existsSync(path.join(l.state, 'root.pub')) && !existsSync(W3PA(l)))
  assert.deepEqual(existsSync(LIB(l)) ? readdirSync(LIB(l)) : [], [], 'no temp files left')
})

test('dry run writes nothing', () => {
  const l = loc(); ok(run(base(l, ['--dry-run'])))
  assert.ok(!existsSync(l.prefix) && !existsSync(l.state))
})

test('full install: files, pinned key, wrapper runs the bundle, launcher syncs then starts Herdr and fails closed', () => {
  const l = loc(); ok(run(base(l, withHerdr)))
  assert.equal(readFileSync(path.join(l.state, 'root.pub'), 'utf8').trim(), KEY)
  assert.equal(sha(path.join(LIB(l), '3pa.mjs')), sha(CLI))
  assert.deepEqual(readdirSync(BIN(l)).sort(), [path.basename(LAUNCH(l)), path.basename(W3PA(l))].sort())
  assert.ok(!readdirSync(LIB(l)).some((f) => f.endsWith('.tmp')))
  if (!WIN) assert.equal(statSync(l.state).mode & 0o777, 0o700)
  const shell = (f, args = []) => (WIN ? spawnSync('cmd.exe', ['/d', '/c', f, ...args], { encoding: 'utf8', env: ENV }) : spawnSync(f, args, { encoding: 'utf8', env: { ...ENV, PATH: `${path.dirname(nodeBin)}:${process.env.PATH}` } }))
  if (!asRoot) { // (as root the launcher would run with root's PATH; the shape is covered below)
    const w = shell(W3PA(l), ['workspace', 'status'])
    assert.match(w.stdout, /3pa-stub workspace status/)
  }
  const launcher = readFileSync(LAUNCH(l), 'utf8')
  assert.ok(launcher.includes(B.replace(/%/g, '%%')) && launcher.includes(l.state) && launcher.includes(l.app))
  assert.ok(launcher.indexOf('workspace sync') < launcher.indexOf(path.basename(LIB(l)) === '3pa' ? 'herdr' : 'x'), 'sync comes before Herdr')
})

test('launcher fails closed: when the sync fails, Herdr is not started (runs the real launcher)', { skip: asRoot }, () => {
  const l = loc(); ok(run(base(l, withHerdr)))
  const env = { ...ENV, PATH: `${path.dirname(nodeBin)}${path.delimiter}${process.env.PATH}` }
  const go = (args = []) => (WIN ? spawnSync('cmd.exe', ['/d', '/c', LAUNCH(l), ...args], { encoding: 'utf8', env }) : spawnSync(LAUNCH(l), args, { encoding: 'utf8', env }))
  // a "Herdr" that prints a marker, and a CLI that succeeds
  const lib3pa = path.join(LIB(l), '3pa.mjs'); const herdr = path.join(LIB(l), WIN ? 'herdr.exe' : 'herdr')
  const r = go(['-e', 'console.log("HERDR-RAN")'])
  assert.match(r.stdout, /3pa-stub workspace sync/); assert.match(r.stdout, /HERDR-RAN/)
  writeFileSync(lib3pa, 'process.exit(3)\n')
  const f = go(['-e', 'console.log("HERDR-RAN")'])
  assert.notEqual(f.status, 0); assert.doesNotMatch(f.stdout, /HERDR-RAN/); assert.match(f.stdout + f.stderr, /not starting Herdr/)
  assert.ok(existsSync(herdr))
})

test('keys: a different pinned root key is refused unless explicit; unreadable or odd targets stop the install', () => {
  const l = loc(); ok(run(base(l)))
  refused(run(base(l).map((x) => (x === KEY ? OTHER : x))), /different root key/)
  assert.equal(readFileSync(path.join(l.state, 'root.pub'), 'utf8').trim(), KEY)
  ok(run(base(l, ['--replace-root']).map((x) => (x === KEY ? OTHER : x))))
  assert.equal(readFileSync(path.join(l.state, 'root.pub'), 'utf8').trim(), OTHER)
  const k = path.join(T, 'root.key.pub'); writeFileSync(k, KEY + '\r\n')
  ok(run(base(l, ['--replace-root']).map((x) => (x === KEY ? k : x))), 'key from a file')
  ok(run(base(l, ['--replace-root']).map((x) => (x === KEY ? k : x))), 'idempotent')
  const m = loc(); mk(path.join(m.state, 'root.pub'))
  refused(run(base(m)), /not a regular file/)
  assert.ok(!existsSync(path.join(m.prefix, 'lib')), 'nothing installed')
  const s = loc(); mk(s.d + path.sep + 'target'); try { symlinkSync(path.join(s.d, 'target'), s.state, 'dir') } catch { return }
  refused(run(base(s)), /link or not a folder/)
  refused(run(base(s).map((x) => (x === s.state ? s.state + path.sep : x))), /link or not a folder/, 'trailing separator')
  refused(run(['--uninstall', '--purge-state', '--prefix', s.prefix, '--state-dir', s.state]), /link or not a folder/)
})

test('destinations must be plain files', () => {
  for (const rel of [['lib', '3pa', '3pa.mjs'], ['bin', WIN ? '3pa.cmd' : '3pa']]) {
    const l = loc(); mk(path.join(l.prefix, ...rel))
    refused(run(base(l)), /not a plain file/, rel.join('/'))
    assert.ok(!existsSync(path.join(l.state, 'root.pub')), 'nothing changed')
  }
})

test('release options: pinned, replaced only on request, purged by name', () => {
  const l = loc(); const RU = 'https://dl.example/release.json'
  refused(run(base(l, ['--release-pub', RK, '--release-url', 'https://u:p@dl.example/r.json'])), /release-url/)
  assert.ok(!existsSync(l.state))
  ok(run(base(l, ['--release-pub', RK, '--release-url', RU])))
  assert.equal(readFileSync(path.join(l.state, 'release.pub'), 'utf8').trim(), RK)
  assert.equal(readFileSync(path.join(l.state, 'release-url'), 'utf8').trim(), RU)
  refused(run(base(l, ['--release-pub', RK2, '--release-url', RU])), /different release key/)
  ok(run(base(l, ['--release-pub', RK2, '--release-url', RU, '--replace-release-key'])))
  assert.equal(readFileSync(path.join(l.state, 'release.pub'), 'utf8').trim(), RK2)
  put(path.join(l.state, 'notes.txt'), 'mine'); put(path.join(l.state, 'release-state.json'), '{}')
  ok(run(['--uninstall', '--purge-state', '--prefix', l.prefix, '--state-dir', l.state]))
  assert.deepEqual(readdirSync(l.state), ['notes.txt'])
  const m = loc(); mk(path.join(m.state, 'release-url'))
  refused(run(base(m, ['--release-pub', RK, '--release-url', RU])), /not a plain file/)
})

test('uninstall: removes only its own files, keeps the key and the app home, purges by exact names', () => {
  const l = loc(); ok(run(base(l, withHerdr)))
  mk(l.app); put(path.join(l.app, 'keep'), 'x'); put(path.join(HOME, 'personal.txt'), 'x')
  put(path.join(LIB(l), 'other'), 'mine')
  ok(run(['--uninstall', '--prefix', l.prefix, '--state-dir', l.state]))
  assert.ok(!existsSync(W3PA(l)) && !existsSync(LAUNCH(l)) && !existsSync(path.join(LIB(l), '3pa.mjs')))
  assert.ok(existsSync(path.join(LIB(l), 'other')), 'a foreign file in our folder survives')
  assert.ok(existsSync(path.join(l.state, 'root.pub')) && existsSync(path.join(l.app, 'keep')))
  const p = loc(); mk(p.state)
  for (const f of ['personal.txt', 'state.json.notes', 'state.jsonl', 'sync.locksmith', '.root.pub.notes', 'root.pub.bak']) put(path.join(p.state, f), 'mine')
  for (const f of ['root.pub', 'state.json', 'state.json.replaced-1730000000000', 'sync.lock', 'sync.lock.takeover', 'sync.lock.tmp-0123456789ab', 'state.json.0123456789ab.tmp']) put(path.join(p.state, f), 'ours')
  ok(run(['--uninstall', '--purge-state', '--prefix', p.prefix, '--state-dir', p.state]))
  assert.deepEqual(readdirSync(p.state).sort(), ['.root.pub.notes', 'personal.txt', 'root.pub.bak', 'state.json.notes', 'state.jsonl', 'sync.lock-notes'.replace('-notes', 'smith')].sort())
  assert.ok(existsSync(path.join(HOME, 'personal.txt')))
  refused(run(['--uninstall', '--dry-run']), /installing only/)
  const q2 = loc()
  refused(run(['--uninstall', '--purge-state', '--prefix', q2.prefix, '--state-dir', HOME]), /may not be/, 'purge of home')
  assert.ok(existsSync(path.join(HOME, 'personal.txt')))
})

test('unicode locations work', () => {
  const l = loc(); const u = path.join(l.d, 'Çağrı-東京'); mk(u)
  ok(run(['--base-url', B, '--root-pub', KEY, '--cli', CLI, '--cli-sha256', sha(CLI), '--prefix', path.join(u, 'p'), '--state-dir', path.join(u, 's'), '--app-home', path.join(u, 'a')]))
  assert.ok(existsSync(path.join(u, 's', 'root.pub')))
})

test('windows only: drive-letter paths, reserved names, streams, trailing dots, % and UNC are refused; the state folder is locked to the user', { skip: !WIN }, () => {
  const l = loc()
  for (const [bad, pat] of [
    [l.prefix.replace(/^[A-Za-z]:/, '\\\\server\\share'), /drive letter/], [`\\\\?\\${l.prefix}`, /drive letter/],
    [path.join(l.d, 'CON'), /reserved device name/], [path.join(l.d, 'nul.txt'), /reserved device name/],
    [path.join(l.d, 'a.'), /dot or a space/], [path.join(l.d, 'a '), /dot or a space/],
    [path.join(l.d, 'x%PATH%'), /< > " \| \? \* or %/], [path.join(l.d, 'a:stream'), /":"|alternate/], [path.join(l.d, 'a<b'), /< > "/],
  ]) refused(run(base(l).map((x) => (x === l.prefix ? bad : x))), pat, bad)
  ok(run(base(l)))
  const acl = spawnSync(path.join(process.env.SystemRoot, 'System32', 'icacls.exe'), [l.state], { encoding: 'utf8' }).stdout
  assert.doesNotMatch(acl, /Everyone|BUILTIN\\Users|Authenticated Users/i, acl)
})

test('windows only: an elevated prompt is refused unless --allow-elevated is given', { skip: !WIN }, () => {
  const l = loc()
  const elevated = spawnSync(path.join(process.env.SystemRoot, 'System32', 'whoami.exe'), ['/groups'], { encoding: 'utf8' }).stdout.includes('S-1-16-12288')
  const r = spawnSync(nodeBin, [INST, ...base(l)], { encoding: 'utf8', env: ENV }) // no flag
  if (elevated) { assert.notEqual(r.status, 0); assert.match(r.stdout + r.stderr, /elevated/); assert.ok(!existsSync(l.prefix)) }
  else assert.equal(r.status, 0, r.stdout + r.stderr)
})
