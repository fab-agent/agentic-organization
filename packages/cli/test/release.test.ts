import assert from 'node:assert/strict'
import { createHash, createPublicKey, generateKeyPairSync, sign as edSign } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, symlinkSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  RELEASE_DOMAIN, ReleaseError, checkReleaseUrl, cleanReleaseState, cmpVersion, emptyReleaseState,
  loadReleaseState, releaseHooks, selfUpdate, verifyRelease, type ReleaseBody, type UpdateOptions,
} from '../src/utils/release.js'
import { canonicalBytes, keyId } from '../src/utils/workspace-manifest.js'

const NOW = 1_800_000_000
const sha = (b: string | Buffer) => createHash('sha256').update(b).digest('hex')

function keypair() {
  const { privateKey, publicKey } = generateKeyPairSync('ed25519')
  const pub = (publicKey.export({ type: 'spki', format: 'der' }) as Buffer).subarray(-32).toString('base64')
  return { privateKey, pub }
}
const K = keypair()
const OTHER = keypair()

function signDoc(body: unknown, k = K, domain = RELEASE_DOMAIN, kid?: string): string {
  const sig = edSign(null, Buffer.concat([Buffer.from(domain, 'ascii'), canonicalBytes(body)]), k.privateKey).toString('base64')
  return JSON.stringify({ body, kid: kid ?? keyId(k.pub), sig })
}

const A3PA = Buffer.from('console.log("3pa v2")\n')
const AHERDR = Buffer.from('#!/bin/sh\necho herdr v2\n')

function body(over: Partial<ReleaseBody> = {}): ReleaseBody {
  return {
    typ: '3pa-release', v: 1, channel: 'stable', version: '1.1.0', seq: 5, issued_at: NOW - 100, expires_at: NOW + 86400,
    artifacts: [
      { name: '3pa', os: 'linux', arch: 'x64', url: 'https://dl.example/3pa-linux-x64', size: A3PA.length, sha256: sha(A3PA) },
      { name: 'herdr', os: 'linux', arch: 'x64', url: 'https://dl.example/herdr-linux-x64', size: AHERDR.length, sha256: sha(AHERDR) },
    ],
    ...over,
  }
}

interface Setup { lib: string; state: string; files: Map<string, Buffer>; seen: { url: string; init?: RequestInit }[]; opts: (o?: Partial<UpdateOptions>) => UpdateOptions; publish: (b: unknown, doc?: string) => void }
function setup(): Setup {
  const root = mkdtempSync(join(tmpdir(), 'rel-'))
  const lib = join(root, 'lib'); const state = join(root, 'state')
  mkdirSync(lib); mkdirSync(state, { mode: 0o700 })
  writeFileSync(join(lib, '3pa.mjs'), 'old 3pa'); writeFileSync(join(lib, 'herdr'), 'old herdr')
  const files = new Map<string, Buffer>([
    ['https://dl.example/3pa-linux-x64', A3PA], ['https://dl.example/herdr-linux-x64', AHERDR],
  ])
  const seen: Setup['seen'] = []
  const fetchImpl = (async (u: string | URL | Request, init?: RequestInit) => {
    const url = String(u); seen.push({ url, init })
    const b = files.get(url)
    if (!b) return new Response('nope', { status: 404 })
    return new Response(b, { status: 200 })
  }) as typeof fetch
  const publish = (b: unknown, doc?: string) => files.set('https://dl.example/release.json', Buffer.from(doc ?? signDoc(b)))
  publish(body())
  return {
    lib, state, files, seen, publish,
    opts: (o = {}) => ({ releaseUrl: 'https://dl.example/release.json', releasePub: K.pub, libDir: lib, stateDir: state, os: 'linux', arch: 'x64', fetchImpl, now: () => NOW * 1000, ...o }),
  }
}
const code = async (p: Promise<unknown>) => { try { await p; return 'ok' } catch (e) { return (e as ReleaseError).code } }
const read = (p: string) => readFileSync(p, 'utf8')

test('happy path: both files replaced, executable, accepted release recorded', async () => {
  const s = setup()
  const r = await selfUpdate(s.opts())
  assert.equal(r.status, 'updated'); assert.deepEqual(r.changed.sort(), ['3pa', 'herdr']); assert.equal(r.version, '1.1.0')
  assert.equal(read(join(s.lib, '3pa.mjs')), A3PA.toString()); assert.equal(read(join(s.lib, 'herdr')), AHERDR.toString())
  assert.equal(statSync(join(s.lib, 'herdr')).mode & 0o777, 0o755)
  assert.equal(loadReleaseState(s.state).channels.stable!.seq, 5)
  assert.deepEqual(readdirSync(s.lib).sort(), ['3pa.mjs', 'herdr'])
  assert.ok(s.seen.every((x) => x.init?.redirect === 'error'), 'redirects are refused on every request')
  assert.equal((await selfUpdate(s.opts())).status, 'up_to_date')
})

test('--check downloads nothing and records nothing', async () => {
  const s = setup()
  const r = await selfUpdate(s.opts({ check: true }))
  assert.equal(r.status, 'available')
  assert.equal(s.seen.length, 1, 'only the signed document was fetched')
  assert.equal(read(join(s.lib, '3pa.mjs')), 'old 3pa')
  assert.ok(!existsSync(join(s.state, 'release-state.json')))
})

test('signature: forged, other key, other domain, tampered body and extra fields are all refused before any download', async () => {
  const cases: [string, string, string][] = [
    ['signed by another key but claiming ours', signDoc(body(), OTHER, RELEASE_DOMAIN, keyId(K.pub)), 'release_bad_signature'],
    ['signed by another key', signDoc(body(), OTHER), 'release_wrong_key'],
    ['another document kind', signDoc(body(), K, 'workspace-manifest-v1\n'), 'release_bad_signature'],
    ['tampered after signing', (() => { const d = JSON.parse(signDoc(body())); d.body.artifacts[0].sha256 = '0'.repeat(64); return JSON.stringify(d) })(), 'release_bad_signature'],
    ['extra envelope field', (() => { const d = JSON.parse(signDoc(body())); d.extra = 1; return JSON.stringify(d) })(), 'release_invalid'],
    ['not JSON', 'nope', 'release_invalid'],
    ['duplicate key', signDoc(body()).replace('"kid"', '"kid":"x","kid"'), 'release_invalid'],
  ]
  for (const [name, doc, want] of cases) {
    const s = setup(); s.publish(null, doc)
    assert.equal(await code(selfUpdate(s.opts())), want, name)
    assert.equal(s.seen.length, 1, `${name}: nothing but the document was fetched`)
    assert.equal(read(join(s.lib, '3pa.mjs')), 'old 3pa'); assert.ok(!existsSync(join(s.state, 'release-state.json')), name)
  }
})

test('body rules: lifetime, expiry, clock, urls, hashes, duplicates, unknown names', async () => {
  const mut = (f: (b: ReleaseBody) => void) => { const b = body(); f(b); return b }
  const cases: [string, ReleaseBody, string][] = [
    ['expired', body({ issued_at: NOW - 200, expires_at: NOW - 1 }), 'release_expired'],
    ['from the future', body({ issued_at: NOW + 10_000, expires_at: NOW + 20_000 }), 'release_not_yet_valid'],
    ['lifetime too long', body({ expires_at: NOW - 100 + 91 * 86400 }), 'release_invalid'],
    ['bad version', body({ version: '1.1' }), 'release_invalid'],
    ['leading zero version', body({ version: '01.1.0' }), 'release_invalid'],
    ['seq zero', body({ seq: 0 }), 'release_invalid'],
    ['http artifact', mut((b) => { b.artifacts[0]!.url = 'http://dl.example/x' }), 'release_invalid'],
    ['credentials in url', mut((b) => { b.artifacts[0]!.url = 'https://u:p@dl.example/x' }), 'release_invalid'],
    ['uppercase hash', mut((b) => { b.artifacts[0]!.sha256 = sha(A3PA).toUpperCase() }), 'release_invalid'],
    ['huge size', mut((b) => { b.artifacts[0]!.size = 201 * 1024 * 1024 }), 'release_invalid'],
    ['unknown artifact', mut((b) => { (b.artifacts[0] as { name: string }).name = 'evil' }), 'release_invalid'],
    ['duplicate artifact', mut((b) => { b.artifacts.push({ ...b.artifacts[0]! }) }), 'release_invalid'],
    ['no artifacts', body({ artifacts: [] }), 'release_invalid'],
    ['extra body field', mut((b) => { (b as unknown as Record<string, unknown>).run = 'rm -rf /' }), 'release_invalid'],
  ]
  for (const [name, b, want] of cases) {
    const s = setup(); s.publish(b)
    assert.equal(await code(selfUpdate(s.opts())), want, name)
    assert.equal(read(join(s.lib, '3pa.mjs')), 'old 3pa', name)
  }
})

test('order: rollback by sequence or version, same sequence with other content; same document again is fine', async () => {
  const s = setup()
  await selfUpdate(s.opts())
  s.publish(body({ seq: 4 })); assert.equal(await code(selfUpdate(s.opts())), 'release_rollback')
  s.publish(body({ seq: 6, version: '1.0.9' })); assert.equal(await code(selfUpdate(s.opts())), 'release_rollback')
  s.publish(body({ seq: 5, version: '1.1.1' })); assert.equal(await code(selfUpdate(s.opts())), 'release_conflict')
  s.publish(body()); assert.equal((await selfUpdate(s.opts())).status, 'up_to_date')
  // a rolled-back document does not touch the files either
  s.publish(body({ seq: 4 })); await code(selfUpdate(s.opts()))
  assert.equal(read(join(s.lib, '3pa.mjs')), A3PA.toString())
  // a newer one moves forward
  const next = Buffer.from('v3'); s.files.set('https://dl.example/3pa-linux-x64', next)
  s.publish(body({ seq: 6, version: '1.2.0', artifacts: [{ ...body().artifacts[0]!, size: next.length, sha256: sha(next) }, body().artifacts[1]!] }))
  assert.deepEqual((await selfUpdate(s.opts())).changed, ['3pa'])
  assert.equal(read(join(s.lib, '3pa.mjs')), 'v3')
})

test('a download that does not match its signed hash or size replaces nothing, not even the good one', async () => {
  for (const evil of [Buffer.from('console.log("evil")\n'), Buffer.concat([A3PA, Buffer.from('x')]), A3PA.subarray(0, 5)]) {
    const s = setup(); s.files.set('https://dl.example/3pa-linux-x64', evil)
    const c = await code(selfUpdate(s.opts()))
    assert.ok(['artifact_mismatch', 'response_too_large'].includes(c), c)
    assert.equal(read(join(s.lib, '3pa.mjs')), 'old 3pa'); assert.equal(read(join(s.lib, 'herdr')), 'old herdr')
    assert.deepEqual(readdirSync(s.lib).sort(), ['3pa.mjs', 'herdr'], 'no temp files left')
  }
})

test('oversize response is cut off by content-length and while streaming', async () => {
  const s = setup()
  const big = Buffer.alloc(A3PA.length + 1000, 1)
  const f = (async (u: string | URL | Request) => {
    const url = String(u)
    if (url.endsWith('release.json')) return new Response(s.files.get(url)!, { status: 200 })
    return new Response(big, { status: 200, headers: { 'content-length': String(big.length) } })
  }) as typeof fetch
  assert.equal(await code(selfUpdate(s.opts({ fetchImpl: f }))), 'response_too_large')
  const g = (async (u: string | URL | Request) => {
    if (String(u).endsWith('release.json')) return new Response(s.files.get(String(u))!, { status: 200 })
    const stream = new ReadableStream({ start(c) { for (let i = 0; i < 50; i++) c.enqueue(new Uint8Array(100)); c.close() } })
    return new Response(stream, { status: 200 })
  }) as typeof fetch
  assert.equal(await code(selfUpdate(s.opts({ fetchImpl: g }))), 'response_too_large')
  assert.equal(read(join(s.lib, '3pa.mjs')), 'old 3pa')
})

test('destinations must be plain files; platform must have a build; time budget is validated', async () => {
  const s = setup()
  const dir = join(s.lib, 'herdr'); require_rm(dir); mkdirSync(dir)
  assert.equal(await code(selfUpdate(s.opts())), 'dest_not_file')
  const t = setup()
  assert.equal(await code(selfUpdate(t.opts({ os: 'macos' }))), 'no_artifact_for_platform')
  assert.equal(await code(selfUpdate(t.opts({ arch: 'arm64' }))), 'no_artifact_for_platform')
  for (const bad of [0, -1, 1.5, Number.NaN, 21 * 60 * 1000, '5' as unknown as number]) {
    assert.equal(await code(selfUpdate(t.opts({ maxDurationMs: bad }))), 'bad_duration', String(bad))
  }
  assert.equal(await code(selfUpdate(t.opts({ channel: 'beta' }))), 'release_wrong_channel')
})
function require_rm(p: string) { execFileSync('rm', ['-f', p]) }

test('time budget: an artifact written after the budget is gone is not published', async () => {
  const s = setup()
  releaseHooks.afterStage = () => { const until = Date.now() + 120; while (Date.now() < until) { /* slow disk */ } }
  try {
    assert.equal(await code(selfUpdate(s.opts({ maxDurationMs: 80 }))), 'update_timeout')
  } finally { releaseHooks.afterStage = undefined }
  assert.equal(read(join(s.lib, '3pa.mjs')), 'old 3pa'); assert.equal(read(join(s.lib, 'herdr')), 'old herdr')
  assert.deepEqual(readdirSync(s.lib).sort(), ['3pa.mjs', 'herdr'])
})

test('urls and state files are parsed strictly', () => {
  assert.equal(checkReleaseUrl('http://localhost:8000/r.json'), 'http://localhost:8000/r.json')
  for (const u of ['http://dl.example/r.json', 'http://localhost.evil.example/r', 'https://u@dl.example/', 'https://dl.example/r#x', 'ftp://x']) {
    assert.throws(() => checkReleaseUrl(u), ReleaseError, u)
  }
  assert.ok(cleanReleaseState(emptyReleaseState()))
  for (const bad of [null, [], { v: 2, channels: {} }, { v: 1, channels: { Bad: { seq: 1, version: '1.0.0', digest: 'a'.repeat(64) } } },
    { v: 1, channels: { stable: { seq: 0, version: '1.0.0', digest: 'a'.repeat(64) } } },
    { v: 1, channels: { stable: { seq: 1, version: '1.0', digest: 'a'.repeat(64) } } },
    { v: 1, channels: { stable: { seq: 1, version: '1.0.0', digest: 'zz' } } },
    { v: 1, channels: { stable: { seq: 1, version: '1.0.0', digest: 'a'.repeat(64), extra: 1 } } }]) {
    assert.equal(cleanReleaseState(bad), null, JSON.stringify(bad))
  }
  assert.equal(cmpVersion('1.10.0', '1.9.9'), 1); assert.equal(cmpVersion('1.0.0', '1.0.0'), 0); assert.equal(cmpVersion('0.9.9', '1.0.0'), -1)
  assert.throws(() => verifyRelease(signDoc(body()), { pub: 'AAAA', now: NOW, state: emptyReleaseState() }), (e: ReleaseError) => e.code === 'bad_release_key')
})

test('real HTTP server: update works, and a redirect is refused', async () => {
  const s = setup()
  const doc = (base: string) => signDoc(body({ artifacts: [
    { name: '3pa', os: 'linux', arch: 'x64', url: `${base}/3pa`, size: A3PA.length, sha256: sha(A3PA) },
    { name: 'herdr', os: 'linux', arch: 'x64', url: `${base}/herdr`, size: AHERDR.length, sha256: sha(AHERDR) },
  ] }))
  let redirect = false
  const srv = createServer((req, res) => {
    const base = `http://127.0.0.1:${(srv.address() as { port: number }).port}`
    if (redirect && req.url === '/3pa') { res.writeHead(302, { location: 'http://127.0.0.1:1/evil' }); return void res.end() }
    if (req.url === '/release.json') return void res.end(doc(base))
    if (req.url === '/3pa') return void res.end(A3PA)
    if (req.url === '/herdr') return void res.end(AHERDR)
    res.writeHead(404); res.end()
  })
  await new Promise<void>((r) => srv.listen(0, '127.0.0.1', r))
  try {
    const url = `http://127.0.0.1:${(srv.address() as { port: number }).port}/release.json`
    const base = s.opts({ releaseUrl: url, fetchImpl: undefined })
    redirect = true
    assert.equal(await code(selfUpdate(base)), 'fetch_failed')
    assert.equal(read(join(s.lib, '3pa.mjs')), 'old 3pa')
    redirect = false
    assert.equal((await selfUpdate(base)).status, 'updated')
    assert.equal(read(join(s.lib, '3pa.mjs')), A3PA.toString())
  } finally { srv.close() }
})

test('signing tool: keygen, sign, verify round trip; refuses to overwrite a key and to sign what the client would refuse', () => {
  const dir = mkdtempSync(join(tmpdir(), 'sign-'))
  const run = (...a: string[]) => execFileSync('npx', ['tsx', 'scripts/release-sign.ts', ...a], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  const out = run('keygen', '--out', dir)
  assert.match(out, /public key/)
  assert.equal(statSync(join(dir, 'release.key')).mode & 0o777, 0o600)
  assert.throws(() => run('keygen', '--out', dir), /refusing to overwrite/)
  const nowS = Math.floor(Date.now() / 1000)
  writeFileSync(join(dir, 'body.json'), JSON.stringify(body({ issued_at: nowS - 10, expires_at: nowS + 3600 })))
  run('sign', '--key', join(dir, 'release.key'), '--body', join(dir, 'body.json'), '--out', join(dir, 'release.json'))
  assert.match(run('verify', '--pub', join(dir, 'release.pub'), '--file', join(dir, 'release.json')), /valid: stable 1\.1\.0 seq 5/)
  writeFileSync(join(dir, 'bad.json'), JSON.stringify(body({ version: 'nope' })))
  assert.throws(() => run('sign', '--key', join(dir, 'release.key'), '--body', join(dir, 'bad.json'), '--out', join(dir, 'x.json')))
  assert.ok(!existsSync(join(dir, 'x.json')))
})

// ═══ CODEX-RELEASE round 1 ═══════════════════════════════════════════════════

test('R1: a damaged, linked or ambiguous release state never resets the history to empty', async () => {
  const good = { v: 1, channels: { stable: { seq: 99, version: '9.0.0', digest: 'a'.repeat(64) } } }
  const make = (write: (dir: string) => void) => { const s = setup(); write(s.state); return s }
  const cases: [string, (dir: string) => void][] = [
    ['duplicate channels key', (d) => writeFileSync(join(d, 'release-state.json'), `{"v":1,"channels":${JSON.stringify(good.channels)},"channels":{}}`)],
    ['dangling symlink', (d) => symlinkSync(join(d, 'nowhere'), join(d, 'release-state.json'))],
    ['symlink to a good file', (d) => { writeFileSync(join(d, 'real.json'), JSON.stringify(good)); symlinkSync(join(d, 'real.json'), join(d, 'release-state.json')) }],
    ['a folder', (d) => mkdirSync(join(d, 'release-state.json'))],
    ['not json', (d) => writeFileSync(join(d, 'release-state.json'), 'x')],
    ['too large', (d) => writeFileSync(join(d, 'release-state.json'), ' '.repeat(70 * 1024))],
  ]
  for (const [name, write] of cases) {
    const s = make(write)
    s.publish(body({ seq: 1, version: '1.0.0' }))
    const c = await code(selfUpdate(s.opts()))
    assert.ok(c === 'state_corrupt' || c === 'state_unreadable', `${name}: ${c}`)
    assert.equal(s.seen.length, 0, `${name}: no request was made`)
    assert.equal(read(join(s.lib, '3pa.mjs')), 'old 3pa', name)
  }
})

test('R2: versions are compared exactly; parts beyond the safe range are refused', async () => {
  assert.equal(cmpVersion('999999999999999.0.0', '999999999999998.0.0'), 1)
  const s = setup(); s.publish(body({ version: '9007199254740993.0.0' }))
  assert.equal(await code(selfUpdate(s.opts())), 'release_invalid')
  s.publish(body({ version: '1234567890123456.0.0' })); assert.equal(await code(selfUpdate(s.opts())), 'release_invalid')
  // near the top of the allowed range, a lower number is still lower
  const t = setup()
  t.publish(body({ seq: 5, version: '999999999999999.0.0' })); await selfUpdate(t.opts({ check: false }))
  t.publish(body({ seq: 6, version: '999999999999998.0.0' })); assert.equal(await code(selfUpdate(t.opts())), 'release_rollback')
})

test('R5: the artifact url must be text', async () => {
  const s = setup()
  const b = body(); (b.artifacts[0] as unknown as { url: unknown }).url = ['https://dl.example/3pa-linux-x64']
  s.publish(b); assert.equal(await code(selfUpdate(s.opts())), 'release_invalid')
  assert.throws(() => checkReleaseUrl(['https://dl.example/x']), (e: ReleaseError) => e.code === 'bad_url')
  assert.throws(() => checkReleaseUrl({ toString: () => 'https://dl.example/x' }), (e: ReleaseError) => e.code === 'bad_url')
})

test('R4: the signing tool never overwrites or follows a link for any output', () => {
  const run = (...a: string[]) => execFileSync('npx', ['tsx', 'scripts/release-sign.ts', ...a], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  const fails = (...a: string[]) => { try { run(...a) } catch (e) { return String((e as { stderr?: string }).stderr) } return null }
  // keygen: a link where release.pub goes (to a note, or dangling to release.key) leaves everything intact
  const d1 = mkdtempSync(join(tmpdir(), 'sg1-')); writeFileSync(join(d1, 'note'), 'mine'); symlinkSync(join(d1, 'note'), join(d1, 'release.pub'))
  assert.match(fails('keygen', '--out', d1) ?? '', /refusing to overwrite/)
  assert.equal(read(join(d1, 'note')), 'mine'); assert.ok(!existsSync(join(d1, 'release.key')))
  const d2 = mkdtempSync(join(tmpdir(), 'sg2-')); symlinkSync(join(d2, 'release.key'), join(d2, 'release.pub'))
  assert.match(fails('keygen', '--out', d2) ?? '', /refusing to overwrite/)
  assert.ok(!existsSync(join(d2, 'release.key')), 'no private key was created next to a link that would destroy it')
  // sign: the output may not be the key, the body, or an earlier document
  const d3 = mkdtempSync(join(tmpdir(), 'sg3-')); run('keygen', '--out', d3)
  const nowS = Math.floor(Date.now() / 1000)
  writeFileSync(join(d3, 'body.json'), JSON.stringify(body({ issued_at: nowS - 10, expires_at: nowS + 3600 })))
  const keyBefore = read(join(d3, 'release.key')), bodyBefore = read(join(d3, 'body.json'))
  assert.match(fails('sign', '--key', join(d3, 'release.key'), '--body', join(d3, 'body.json'), '--out', join(d3, 'release.key')) ?? '', /refusing to overwrite/)
  assert.match(fails('sign', '--key', join(d3, 'release.key'), '--body', join(d3, 'body.json'), '--out', join(d3, 'body.json')) ?? '', /refusing to overwrite/)
  assert.equal(read(join(d3, 'release.key')), keyBefore); assert.equal(read(join(d3, 'body.json')), bodyBefore)
  symlinkSync(join(d3, 'release.key'), join(d3, 'out.json'))
  assert.match(fails('sign', '--key', join(d3, 'release.key'), '--body', join(d3, 'body.json'), '--out', join(d3, 'out.json')) ?? '', /refusing to overwrite|EEXIST/)
  assert.equal(read(join(d3, 'release.key')), keyBefore)
  run('sign', '--key', join(d3, 'release.key'), '--body', join(d3, 'body.json'), '--out', join(d3, 'ok.json'))
  assert.match(fails('sign', '--key', join(d3, 'release.key'), '--body', join(d3, 'body.json'), '--out', join(d3, 'ok.json')) ?? '', /refusing to overwrite/)
})

test('R7: what the updater writes can always be read back; a full state refuses a new channel and stays intact', async () => {
  const mk = (n: number) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`ch${String.fromCharCode(97 + (i % 26))}${Math.floor(i / 26)}`, { seq: 99999999, version: '999999999999999.999999999999999.999999999999999', digest: 'a'.repeat(64) }]))
  // the largest state allowed is far below the reader's limit and round-trips
  const s = setup()
  writeFileSync(join(s.state, 'release-state.json'), JSON.stringify({ v: 1, channels: mk(15) }))
  await selfUpdate(s.opts()) // adds "stable" as the 16th
  assert.equal(Object.keys(loadReleaseState(s.state).channels).length, 16)
  assert.ok(statSync(join(s.state, 'release-state.json')).size < 16 * 1024)
  await selfUpdate(s.opts()) // and is read back on the next run
  // a 17th channel is refused before any file is touched, and the old state is kept
  const t = setup()
  const full = JSON.stringify({ v: 1, channels: mk(16) })
  writeFileSync(join(t.state, 'release-state.json'), full)
  assert.equal(await code(selfUpdate(t.opts())), 'release_state_full')
  assert.equal(read(join(t.state, 'release-state.json')), full)
  assert.equal(read(join(t.lib, '3pa.mjs')), 'old 3pa')
  // a state with more channels than the policy allows is not valid input either
  assert.equal(cleanReleaseState({ v: 1, channels: mk(17) }), null)
})
