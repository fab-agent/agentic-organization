import assert from 'node:assert/strict'
import {
  createHash, createPrivateKey, generateKeyPairSync, sign as edSign, type KeyObject,
} from 'node:crypto'
import {
  existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, test } from 'node:test'

import {
  ProvisionError, SHIPPED_MODS, checkBaseUrl, cleanManaged, ensureTelemetryOff, recoverInterrupted, scanDrift, syncWorkspace,
} from '../src/utils/provisioner.ts'
import { writeAll } from '../src/utils/fsutil.ts'
import { lockHooks } from '../src/utils/workspace-state.ts'
import { canonicalBytes, keyId } from '../src/utils/workspace-manifest.ts'
import { cleanState, loadState, saveState, withLock, freshState, StateError } from '../src/utils/workspace-state.ts'

const NOW = 1_800_000_000
const DOM = { cert: 'fab-signing-cert-v1\n', crl: 'fab-crl-v1\n', manifest: 'fab-workspace-manifest-v1\n' }

function keypair(): { priv: KeyObject; pub: string } {
  const { privateKey, publicKey } = generateKeyPairSync('ed25519')
  const pub = publicKey.export({ type: 'spki', format: 'der' }).subarray(-32).toString('base64')
  return { priv: createPrivateKey(privateKey.export({ type: 'pkcs8', format: 'pem' })), pub }
}
const signDoc = (priv: KeyObject, kind: keyof typeof DOM, payload: unknown) =>
  edSign(null, Buffer.concat([Buffer.from(DOM[kind]), canonicalBytes(payload)]), priv).toString('base64')
const sha = (b: Buffer | string) => createHash('sha256').update(b).digest('hex')

interface Content { layout: string; mods: Record<string, Record<string, string>> }

/** A fake platform: signs real manifests and serves the files; knobs for every failure. */
class World {
  root = keypair()
  signing = keypair()
  epoch = 1
  generation = 0
  forceGeneration: number | null = null
  person = { company_id: 'co1', person_id: 'p1' }
  layoutId = 'finance-v2'
  version = '1.0.0'
  content: Content = { layout: '{"id":"finance"}', mods: { 'finance-dashboard': { 'main.js': 'export default 1;\n', 'assets/icon.svg': '<svg/>' } } }
  tamper = new Set<string>()
  oversize = new Set<string>()
  short = new Set<string>()
  crl: unknown = null
  mutate: ((p: Record<string, unknown>) => void) | null = null
  failManifest: Response | null = null
  files = new Map<string, Buffer>()
  calls: string[] = []

  cert() {
    const payload = {
      typ: 'fab-signing-cert', v: 1, kid: keyId(this.signing.pub), pub: this.signing.pub,
      issuer_kid: keyId(this.root.pub), not_before: NOW - 3600, not_after: NOW + 30 * 86400, serial: 1, epoch: this.epoch,
    }
    return { payload, sig: signDoc(this.root.priv, 'cert', payload) }
  }

  manifest() {
    this.files.clear()
    const layoutBytes = Buffer.from(this.content.layout)
    this.files.set(sha(layoutBytes), layoutBytes)
    const mods = Object.entries(this.content.mods).map(([name, fs]) => ({
      name, version: this.version,
      files: Object.entries(fs).map(([path, text]) => {
        const b = Buffer.from(text)
        this.files.set(sha(b), b)
        return { path, sha256: sha(b), size: b.length }
      }),
    }))
    this.generation = this.forceGeneration ?? this.generation + 1
    const payload = {
      typ: 'fab-workspace-manifest', v: 1, epoch: this.epoch, ...this.person, aud: 'herdr-provisioner',
      generation: this.generation, issued_at: NOW - 60, expires_at: NOW + 3600, min_client_version: '0.0.0',
      gateway_url: 'https://gw.example.test',
      layout: { id: this.layoutId, sha256: sha(layoutBytes), size: layoutBytes.length }, mods,
    }
    this.mutate?.(payload)
    return { cert: this.cert(), payload, sig: signDoc(this.signing.priv, 'manifest', payload) }
  }

  fetchImpl: typeof fetch = async (url) => {
    const u = new URL(String(url))
    this.calls.push(u.pathname)
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
    if (u.pathname === '/me/workspace/crl') return this.crl ? json(200, this.crl) : json(404, { detail: 'none' })
    if (u.pathname === '/me/workspace') {
      if (this.failManifest) return this.failManifest.clone()
      const manifest = this.manifest()
      return json(200, {
        manifest, identity: this.person,
        bootstrap: { min_generation: this.generation, min_epoch: this.epoch, min_crl_number: 0 },
      })
    }
    const m = /^\/me\/workspace\/files\/([0-9a-f]{64})$/.exec(u.pathname)
    if (m) {
      const h = m[1]!
      const b = this.files.get(h)
      if (!b) return json(404, { detail: 'Not part of your workspace' })
      if (this.tamper.has(h)) return new Response(Buffer.from('X'.repeat(b.length)))
      if (this.oversize.has(h)) return new Response(Buffer.concat([b, Buffer.from('extra')]))
      if (this.short.has(h)) return new Response(b.subarray(0, b.length - 1))
      return new Response(b)
    }
    return json(404, {})
  }
}

const dirs: string[] = []
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true })
})

function setup(w = new World()) {
  const base = mkdtempSync(join(tmpdir(), 'prov-'))
  dirs.push(base)
  const appHome = join(base, 'app')
  const stateDir = join(base, 'state')
  const opts = (extra: Record<string, unknown> = {}) => ({
    baseUrl: 'https://platform.example.test', webToken: 'web-jwt', rootPub: w.root.pub, appHome, stateDir,
    clientVersion: '1.0.0', now: () => NOW, fetchImpl: w.fetchImpl, ...extra,
  })
  return { w, base, appHome, stateDir, opts }
}

const read = (p: string) => readFileSync(p, 'utf8')
const leftovers = (appHome: string) => readdirSync(appHome).filter((n) => n.startsWith('.3pa-staging-') || n.startsWith('.3pa-trash-'))
const code = async (p: Promise<unknown>) => {
  try { await p } catch (e) { return (e as { code?: string }).code ?? String(e) }
  return 'NO_ERROR'
}

// ── happy path ───────────────────────────────────────────────────────────────

test('installs the layout and mods, records what it manages, and turns telemetry off', async () => {
  const { w, appHome, stateDir, opts } = setup()
  const r = await syncWorkspace(opts())
  assert.equal(r.status, 'updated')
  assert.equal(r.generation, 1)
  assert.equal(read(join(appHome, 'layouts', 'finance-v2.json')), w.content.layout)
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), 'export default 1;\n')
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'assets', 'icon.svg')), '<svg/>')
  assert.deepEqual(JSON.parse(read(join(appHome, 'settings.json'))), { telemetry: false })
  const managed = JSON.parse(read(join(appHome, '.3pa-managed.json')))
  assert.equal(managed.layout.name, 'finance-v2')
  assert.deepEqual(Object.keys(managed.mods), ['finance-dashboard'])
  const st = loadState(stateDir)!
  assert.equal(st.client.epoch, 1)
  assert.deepEqual(st.identity, { company_id: 'co1', person_id: 'p1' })
  assert.equal(st.installed?.generation, 1)
  assert.deepEqual(leftovers(appHome), [])
  assert.equal(lstatSync(join(stateDir, 'state.json')).mode & 0o777, 0o600)
  assert.deepEqual(scanDrift(appHome), { missing: [], modified: [], unmanagedMods: [], extraFiles: [], interrupted: false })
})

test('unchanged content is a no-op even though the server issues a new generation', async () => {
  const { w, stateDir, opts } = setup()
  await syncWorkspace(opts())
  const r = await syncWorkspace(opts())
  assert.equal(r.status, 'unchanged')
  assert.equal(r.generation, 2)
  assert.equal(loadState(stateDir)!.installed?.generation, 2)
  assert.equal(w.calls.filter((c) => c.startsWith('/me/workspace/files/')).length, 3) // only the first sync downloaded
})

test('changed content replaces only what changed and removes what the manifest dropped', async () => {
  const { w, appHome, opts } = setup()
  w.content.mods['old-panel'] = { 'main.js': 'old' }
  await syncWorkspace(opts())
  assert.ok(existsSync(join(appHome, 'mods', 'old-panel')))
  delete w.content.mods['old-panel']
  w.content.mods['finance-dashboard']!['main.js'] = 'export default 2;\n'
  w.version = '1.1.0'
  const r = await syncWorkspace(opts())
  assert.equal(r.status, 'updated')
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), 'export default 2;\n')
  assert.ok(!existsSync(join(appHome, 'mods', 'old-panel')))
  assert.deepEqual(leftovers(appHome), [])
})

test('a managed file deleted or edited by hand is repaired on the next sync', async () => {
  const { appHome, opts } = setup()
  await syncWorkspace(opts())
  writeFileSync(join(appHome, 'mods', 'finance-dashboard', 'main.js'), 'tampered')
  assert.deepEqual(scanDrift(appHome).modified, ['mods/finance-dashboard/main.js'])
  const r = await syncWorkspace(opts())
  assert.equal(r.status, 'updated')
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), 'export default 1;\n')
})

// ── downloads are verified before anything goes live ─────────────────────────

test('a tampered, short or oversized download aborts and leaves the live workspace untouched', async () => {
  for (const knob of ['tamper', 'short', 'oversize'] as const) {
    const { w, appHome, opts } = setup()
    await syncWorkspace(opts())
    const before = read(join(appHome, 'mods', 'finance-dashboard', 'main.js'))
    w.content.mods['finance-dashboard']!['main.js'] = 'export default 99;\n'
    // the server flags the new file after the manifest has been issued
    w[knob].add(sha(Buffer.from('export default 99;\n')))
    const c = await code(syncWorkspace(opts()))
    assert.match(c, /^(file_|response_too_large)/, `${knob}: ${c}`)
    assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), before, knob)
    assert.deepEqual(leftovers(appHome), [], knob)
  }
})

test('a failed activation puts the previous workspace back exactly', async () => {
  const { w, appHome, opts } = setup()
  await syncWorkspace(opts())
  w.content.mods['finance-dashboard']!['main.js'] = 'v2'
  w.content.layout = '{"id":"finance","v":2}'
  let n = 0
  const fsOps = {
    rename: (a: string, b: string) => {
      if (++n === 4) throw new Error('disk full') // after the old items were moved aside
      return renameReal(a, b)
    },
  }
  const c = await code(syncWorkspace(opts({ fsOps })))
  assert.equal(c, 'activation_failed')
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), 'export default 1;\n')
  assert.equal(read(join(appHome, 'layouts', 'finance-v2.json')), '{"id":"finance"}')
  assert.deepEqual(leftovers(appHome), [])
  assert.deepEqual(scanDrift(appHome).modified, [])
})
import { renameSync as renameReal } from 'node:fs'
import { spawnSync } from 'node:child_process'

// ── what it will not touch ───────────────────────────────────────────────────

test('refuses to replace a mod it does not manage, unless told to adopt it', async () => {
  const { appHome, opts } = setup()
  mkdirSync(join(appHome, 'mods', 'finance-dashboard'), { recursive: true })
  writeFileSync(join(appHome, 'mods', 'finance-dashboard', 'mine.js'), 'my own work')
  assert.equal(await code(syncWorkspace(opts())), 'unmanaged_exists')
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'mine.js')), 'my own work')
  assert.equal(existsSync(join(appHome, 'layouts', 'finance-v2.json')), false) // nothing was applied
  await syncWorkspace(opts({ adopt: true }))
  assert.ok(!existsSync(join(appHome, 'mods', 'finance-dashboard', 'mine.js')))
  assert.deepEqual(leftovers(appHome), [])
})

test('refuses names Herdr ships (it rewrites them on every start)', async () => {
  for (const [kind, name] of [['mod', 'files'], ['mod', 'win98'], ['layout', 'main'], ['layout', 'terminals']] as const) {
    const { w, opts } = setup()
    if (kind === 'mod') w.content.mods = { [name]: { 'main.js': 'x' } }
    else w.layoutId = name
    assert.equal(await code(syncWorkspace(opts())), 'shipped_name', `${kind} ${name}`)
  }
  assert.ok(SHIPPED_MODS.has('workspace-chrome'))
})

test('a link in the app home is refused, never followed', async () => {
  const a = setup()
  const outside = join(a.base, 'outside')
  mkdirSync(outside)
  mkdirSync(a.appHome)
  symlinkSync(outside, join(a.appHome, 'mods'))
  assert.equal(await code(syncWorkspace(a.opts())), 'app_home_unsafe')
  assert.deepEqual(readdirSync(outside), [])

  const b = setup()
  const real = join(b.base, 'real')
  mkdirSync(real)
  symlinkSync(real, b.appHome)
  assert.equal(await code(syncWorkspace(b.opts())), 'app_home_unsafe')
  assert.deepEqual(readdirSync(real), [])
})

test('settings.json keeps other settings, and an unreadable one is left alone', async () => {
  const a = setup()
  mkdirSync(a.appHome)
  writeFileSync(join(a.appHome, 'settings.json'), JSON.stringify({ zoom: 1.5, sounds: { enabled: false } }))
  await syncWorkspace(a.opts())
  assert.deepEqual(JSON.parse(read(join(a.appHome, 'settings.json'))), { zoom: 1.5, sounds: { enabled: false }, telemetry: false })

  const b = setup()
  mkdirSync(b.appHome)
  writeFileSync(join(b.appHome, 'settings.json'), '{not json')
  assert.equal(await code(syncWorkspace(b.opts())), 'settings_invalid')
  assert.equal(read(join(b.appHome, 'settings.json')), '{not json')
  assert.equal(loadState(b.stateDir), null) // nothing was accepted either
  assert.throws(() => ensureTelemetryOff(b.appHome), ProvisionError)
})

// ── trust: identity, replay, revocation, corrupt state ───────────────────────

test('a lower generation than the accepted one is refused', async () => {
  const { w, opts } = setup()
  w.generation = 4
  await syncWorkspace(opts())
  w.forceGeneration = 2
  assert.equal(await code(syncWorkspace(opts())), 'manifest_rollback')
})

test('the first identity is pinned; a different person is refused', async () => {
  const { w, opts } = setup()
  await syncWorkspace(opts())
  w.person = { company_id: 'co1', person_id: 'p2' }
  assert.equal(await code(syncWorkspace(opts())), 'identity_changed')
  await syncWorkspace(opts({ reEnroll: true })) // an explicit decision
})

test('a manifest signed by a key the root did not certify is refused', async () => {
  const { w, appHome, opts } = setup()
  const rogue = keypair()
  w.root = rogue // the server now signs with a different root than the one pinned
  const pinned = opts()
  const c = await code(syncWorkspace({ ...pinned, rootPub: keypair().pub }))
  assert.match(c, /^manifest_(bad_signature|bad_cert)$/)
  assert.ok(!existsSync(join(appHome, 'layouts', 'finance-v2.json')))
})

test('a revoked signing key is refused and the revocation list is kept', async () => {
  const { w, stateDir, opts } = setup()
  const payload = { typ: 'fab-crl', v: 1, number: 1, revoked_kids: [keyId(w.signing.pub)], issued_at: NOW - 10, next_update: NOW + 86400 }
  w.crl = { payload, sig: signDoc(w.root.priv, 'crl', payload) }
  assert.equal(await code(syncWorkspace(opts())), 'manifest_cert_revoked')
  const st = loadState(stateDir)!
  assert.equal(st.client.crl_number, 1)
  assert.deepEqual(st.client.revoked, [keyId(w.signing.pub)])
})

test('a corrupt state file is never reset silently', async () => {
  const { stateDir, opts, appHome } = setup()
  await syncWorkspace(opts())
  writeFileSync(join(stateDir, 'state.json'), '{"v":1,"client":')
  assert.equal(await code(syncWorkspace(opts())), 'state_corrupt')
  assert.ok(existsSync(join(appHome, 'layouts', 'finance-v2.json')))
  await syncWorkspace(opts({ reEnroll: true })) // the operator's explicit choice
  assert.ok(readdirSync(stateDir).some((n) => n.startsWith('state.json.replaced-'))) // kept aside
  assert.equal(loadState(stateDir)!.installed?.generation, 2)
})

test('a server that cannot sign says why, without a stack trace', async () => {
  const { w, opts } = setup()
  w.fetchImpl = async () => new Response(JSON.stringify({ detail: { error: 'workspace_unavailable', reason: 'signing_key_revoked' } }), { status: 503 })
  assert.equal(await code(syncWorkspace(opts())), 'server_signing_key_revoked')
})

test('the bearer token is never sent anywhere else (redirects are errors)', async () => {
  const { w, opts } = setup()
  const seen: RequestInit[] = []
  const orig = w.fetchImpl
  w.fetchImpl = async (u, i) => { seen.push(i ?? {}); return orig(u, i) }
  await syncWorkspace(opts())
  assert.ok(seen.length > 0 && seen.every((i) => i.redirect === 'error'))
})

// ── state file and lock ──────────────────────────────────────────────────────

test('state is written atomically with private permissions and a lock keeps a second run out', async () => {
  const { stateDir } = setup()
  saveState(stateDir, freshState())
  assert.equal(lstatSync(stateDir).mode & 0o777, 0o700)
  const events: string[] = []
  const first = withLock(stateDir, async () => {
    events.push('first-in')
    await new Promise((r) => setTimeout(r, 50))
    events.push('first-out')
  })
  await new Promise((r) => setTimeout(r, 10))
  const second = await code(withLock(stateDir, async () => { events.push('second') }))
  await first
  assert.equal(second, 'locked')
  assert.deepEqual(events, ['first-in', 'first-out'])
  await withLock(stateDir, async () => { events.push('after') }) // lock was released
  assert.equal(events.at(-1), 'after')
})

test('a lock left by a dead process is taken over', async () => {
  const { stateDir } = setup()
  saveState(stateDir, freshState())
  writeFileSync(join(stateDir, 'sync.lock'), '999999999')
  let ran = false
  await withLock(stateDir, async () => { ran = true })
  assert.ok(ran)
})

test('a state directory that is a link or not private is refused', () => {
  const { base } = setup()
  const real = join(base, 'real')
  mkdirSync(real, { mode: 0o700 })
  symlinkSync(real, join(base, 'linked'))
  assert.throws(() => saveState(join(base, 'linked'), freshState()), (e: StateError) => e.code === 'state_dir_unsafe')
})

// ── drift ────────────────────────────────────────────────────────────────────

test('drift lists missing, modified, extra and unmanaged mods, but not Herdr built-ins', async () => {
  const { appHome, opts } = setup()
  await syncWorkspace(opts())
  writeFileSync(join(appHome, 'mods', 'finance-dashboard', 'main.js'), 'edited')
  rmSync(join(appHome, 'mods', 'finance-dashboard', 'assets', 'icon.svg'))
  writeFileSync(join(appHome, 'mods', 'finance-dashboard', 'extra.js'), 'x')
  mkdirSync(join(appHome, 'mods', 'rogue'))
  mkdirSync(join(appHome, 'mods', 'files')) // shipped by Herdr
  assert.deepEqual(scanDrift(appHome), {
    missing: ['mods/finance-dashboard/assets/icon.svg'],
    modified: ['mods/finance-dashboard/main.js'],
    unmanagedMods: ['rogue'],
    extraFiles: ['mods/finance-dashboard/extra.js'],
    interrupted: false,
  })
})

// ═══ CODEX-PROVISIONER ═══════════════════════════════════════════════════════

import { mkdirSync as mk, existsSync as ex, lstatSync as ls, readdirSync as rd, writeFileSync as wf, symlinkSync as sl, readFileSync as rf, rmSync as rm } from 'node:fs'
import { webSignIn } from '../src/commands/login.ts'

// P-01 ── a name like "constructor" is data, not a prototype member ──────────────

test('P-01: a signed mod named "constructor" cannot overwrite an unmanaged folder of that name', async () => {
  const { w, appHome, opts } = setup()
  w.content.mods = { constructor: { 'main.js': 'x' } }
  mk(join(appHome, 'mods', 'constructor'), { recursive: true })
  wf(join(appHome, 'mods', 'constructor', 'mine.txt'), 'my own work')
  assert.equal(await code(syncWorkspace(opts())), 'unmanaged_exists')
  assert.equal(rf(join(appHome, 'mods', 'constructor', 'mine.txt'), 'utf8'), 'my own work')
})

test('P-01: an unmanaged "constructor" folder shows up as unmanaged in the drift scan', async () => {
  const { appHome, opts } = setup()
  await syncWorkspace(opts())
  mk(join(appHome, 'mods', 'constructor'))
  mk(join(appHome, 'mods', 'toString'))
  assert.deepEqual(scanDrift(appHome).unmanagedMods.sort(), ['constructor', 'toString'])
})

test('P-01: a managed record cannot smuggle prototype keys', () => {
  assert.equal(cleanManaged(JSON.parse('{"v":1,"layout":null,"mods":{"__proto__":{"version":"1.0.0","files":{}}}}'))?.mods.constructor, undefined)
  assert.ok(cleanManaged({ v: 1, layout: null, mods: {} }))
})

// P-02 ── a rollback that fails must never delete the only copy ───────────────────

test('P-02: when the rollback itself fails, the previous items are kept and the sync says so', async () => {
  const { w, appHome, opts } = setup()
  await syncWorkspace(opts())
  w.content.mods['finance-dashboard']!['main.js'] = 'v2'
  let n = 0
  const fsOps = {
    rename: (a: string, b: string) => {
      n++
      if (n >= 4) throw Object.assign(new Error('disk gone'), { code: 'EIO' }) // the new item AND every restore fail
      renameReal(a, b)
    },
  }
  assert.equal(await code(syncWorkspace(opts({ fsOps }))), 'recovery_required')
  const saved = readdirSync(appHome).filter((x) => x.startsWith('.3pa-trash-'))
  assert.equal(saved.length, 1, 'the trash with the old items must still exist')
  assert.ok(readdirSync(join(appHome, saved[0]!)).length > 0)
  assert.ok(ex(join(appHome, '.3pa-journal.json')), 'the journal stays so the next run can finish')
  // the next run (fs healthy again) finishes the rollback, then installs
  const r = await syncWorkspace(opts())
  assert.equal(r.status, 'updated')
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), 'v2')
  assert.deepEqual(leftovers(appHome), [])
  assert.ok(!ex(join(appHome, '.3pa-journal.json')))
})

// P-03 ── the managed record is part of the transaction; a crash is recovered ────

test('P-03a: a failing managed-record write rolls the live items back too', async () => {
  const { w, appHome, opts } = setup()
  await syncWorkspace(opts())
  w.content.mods['finance-dashboard']!['main.js'] = 'v2'
  const fsOps = {
    rename: (a: string, b: string) => {
      if (b.endsWith('.3pa-managed.json')) throw Object.assign(new Error('EIO'), { code: 'EIO' })
      renameReal(a, b)
    },
  }
  assert.equal(await code(syncWorkspace(opts({ fsOps }))), 'activation_failed')
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), 'export default 1;\n')
  assert.deepEqual(scanDrift(appHome).modified, [])
  assert.deepEqual(leftovers(appHome), [])
  assert.ok(!ex(join(appHome, '.3pa-journal.json')))
})

test('P-03b: a process killed in the middle of an activation is rolled back on the next start', async () => {
  for (const crashAt of [1, 2, 3, 4]) {
    const { w, base, appHome, stateDir, opts } = setup()
    await syncWorkspace(opts())
    const before = {
      layout: read(join(appHome, 'layouts', 'finance-v2.json')),
      main: read(join(appHome, 'mods', 'finance-dashboard', 'main.js')),
      managed: read(join(appHome, '.3pa-managed.json')),
    }
    w.content.mods['finance-dashboard']!['main.js'] = 'v2'
    w.content.layout = '{"id":"finance","v":2}'
    // record the platform's answers for the child
    const replay: Record<string, { status: number; body: string }> = {}
    for (const p of ['/me/workspace/crl', '/me/workspace']) {
      const r = await w.fetchImpl(`https://x.test${p}`)
      replay[p] = { status: r.status, body: Buffer.from(await r.arrayBuffer()).toString('base64') }
    }
    for (const [h, b] of w.files) replay[`/me/workspace/files/${h}`] = { status: 200, body: b.toString('base64') }
    const cfg = join(base, 'crash.json')
    wf(cfg, JSON.stringify({ replay, baseUrl: 'https://platform.example.test', rootPub: w.root.pub, appHome, stateDir, now: NOW, crashAtRename: crashAt }))
    const fx = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'crash-sync.mts')
    const child = spawnSync(process.execPath, ['--import', 'tsx', fx, cfg], { encoding: 'utf8' })
    assert.equal(child.status, 73, `crash at ${crashAt}: ${child.stderr}`)
    assert.ok(ex(join(appHome, '.3pa-journal.json')), 'the journal survived the crash')

    assert.equal(recoverInterrupted(appHome), true)
    assert.equal(read(join(appHome, 'layouts', 'finance-v2.json')), before.layout, `crash at ${crashAt}`)
    assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), before.main, `crash at ${crashAt}`)
    assert.equal(read(join(appHome, '.3pa-managed.json')), before.managed, `crash at ${crashAt}`)
    assert.deepEqual(leftovers(appHome), [])
    assert.ok(!ex(join(appHome, '.3pa-journal.json')))
    assert.deepEqual(scanDrift(appHome).modified, [])
  }
})
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

test('P-03c: after a failed update the next sync installs it', async () => {
  const { w, appHome, opts } = setup()
  await syncWorkspace(opts())
  w.content.mods['finance-dashboard']!['main.js'] = 'v2'
  let n = 0
  await syncWorkspace(opts({ fsOps: { rename: (a: string, b: string) => { if (++n === 2) throw Object.assign(new Error('x'), { code: 'EIO' }); renameReal(a, b) } } })).catch(() => undefined)
  const r = await syncWorkspace(opts())
  assert.equal(r.status, 'updated')
  assert.equal(read(join(appHome, 'mods', 'finance-dashboard', 'main.js')), 'v2')
})

test('P-03d: a damaged or foreign journal is refused, never obeyed', () => {
  const { appHome } = setup()
  mk(appHome, { recursive: true })
  const journal = (j: unknown) => wf(join(appHome, '.3pa-journal.json'), JSON.stringify(j))
  const evil = { v: 1, trash: '/etc', staging: join(appHome, '.3pa-staging-x'), ops: [], prevManaged: null }
  journal(evil)
  assert.throws(() => recoverInterrupted(appHome), (e: ProvisionError) => e.code === 'recovery_required')
  journal({ v: 1, trash: join(appHome, '.3pa-trash-x'), staging: join(appHome, '.3pa-staging-x'), ops: [{ live: '../../etc/passwd', hadLive: true, aside: null, staged: null }], prevManaged: null })
  assert.throws(() => recoverInterrupted(appHome), (e: ProvisionError) => e.code === 'recovery_required')
  wf(join(appHome, '.3pa-journal.json'), '{not json')
  assert.throws(() => recoverInterrupted(appHome), (e: ProvisionError) => e.code === 'recovery_required')
})

// P-04 ── the lock ───────────────────────────────────────────────────────────────

test('P-04: a takeover that finds a LIVE lock where it expected a stale one puts it back and backs off', async () => {
  const { stateDir } = setup()
  saveState(stateDir, freshState())
  const lock = join(stateDir, 'sync.lock')
  wf(lock, JSON.stringify({ pid: 999999999, token: 'stale' })) // dead owner
  lockHooks.afterReadStale = () => {
    // meanwhile another run took over and now holds the lock for real
    rm(lock)
    wf(lock, JSON.stringify({ pid: process.pid, token: 'LIVE' }))
  }
  try {
    assert.equal(await code(withLock(stateDir, async () => 'must not run')), 'locked')
  } finally {
    lockHooks.afterReadStale = undefined
  }
  assert.deepEqual(JSON.parse(rf(lock, 'utf8')), { pid: process.pid, token: 'LIVE' }) // still there, intact
  assert.ok(!rd(stateDir).some((n) => n.includes('.stale-')), 'no leftovers')
  rm(lock)
})

test('P-04: unlock never removes a lock that is not ours, and assertOwned notices', async () => {
  const { stateDir } = setup()
  saveState(stateDir, freshState())
  const lock = join(stateDir, 'sync.lock')
  await withLock(stateDir, async (assertOwned) => {
    assertOwned()
    rm(lock)
    wf(lock, JSON.stringify({ pid: process.pid, token: 'SOMEONE-ELSE' }))
    assert.throws(() => assertOwned(), (e: StateError) => e.code === 'lock_lost')
  })
  assert.ok(ex(lock), "another run's lock was left alone")
  assert.equal(JSON.parse(rf(lock, 'utf8')).token, 'SOMEONE-ELSE')
  rm(lock)
})

test('P-04: a sync stops before writing when it has lost the lock', async () => {
  const { w, appHome, stateDir, opts } = setup()
  const orig = w.fetchImpl
  w.fetchImpl = async (u, i) => {
    const r = await orig(u, i)
    if (new URL(String(u)).pathname === '/me/workspace') { rm(join(stateDir, 'sync.lock')); wf(join(stateDir, 'sync.lock'), JSON.stringify({ pid: process.pid, token: 'OTHER' })) }
    return r
  }
  assert.equal(await code(syncWorkspace(opts())), 'lock_lost')
  assert.ok(!ex(join(appHome, 'layouts', 'finance-v2.json')))
  rm(join(stateDir, 'sync.lock'))
})

// P-05 ── a revocation list survives an unavailable manifest ─────────────────────

test('P-05: the revocation list is saved even when the manifest request fails', async () => {
  const { w, stateDir, opts } = setup()
  await syncWorkspace(opts()) // enrolled with the current signing key
  const kid = keyId(w.signing.pub)
  const payload = { typ: 'fab-crl', v: 1, number: 1, revoked_kids: [kid], issued_at: NOW - 10, next_update: NOW + 86400 }
  w.crl = { payload, sig: signDoc(w.root.priv, 'crl', payload) }
  w.failManifest = new Response(JSON.stringify({ detail: { error: 'workspace_unavailable', reason: 'catalog_changed' } }), { status: 503 })
  assert.equal(await code(syncWorkspace(opts())), 'server_catalog_changed')
  const st = loadState(stateDir)!
  assert.equal(st.client.crl_number, 1)
  assert.deepEqual(st.client.revoked, [kid])
})

test('P-05: a CRL with a bad signature is refused outright', async () => {
  const { w, opts } = setup()
  const payload = { typ: 'fab-crl', v: 1, number: 1, revoked_kids: [], issued_at: NOW - 10, next_update: NOW + 86400 }
  w.crl = { payload, sig: signDoc(keypair().priv, 'crl', payload) }
  assert.equal(await code(syncWorkspace(opts())), 'crl_bad_signature')
})

// P-06 ── every byte reaches the disk ────────────────────────────────────────────

test('P-06: short writes are completed, and no progress is an error', () => {
  const base = mkdtempSync(join(tmpdir(), 'w-'))
  dirs.push(base)
  const path = join(base, 'f')
  const fd = openFd(path, 'w')
  const calls: number[] = []
  writeAll(fd, Buffer.from('hello world'), (f, buf, off, len) => {
    calls.push(len)
    return writeSyncReal(f, buf, off, Math.min(len, 3)) // never more than 3 bytes at a time
  })
  closeFd(fd)
  assert.equal(rf(path, 'utf8'), 'hello world')
  assert.ok(calls.length >= 4)
  const fd2 = openFd(join(base, 'g'), 'w')
  assert.throws(() => writeAll(fd2, Buffer.from('abc'), () => 0), (e: { code: string }) => e.code === 'write_failed')
  closeFd(fd2)
})
import { closeSync as closeFd, openSync as openFd, writeSync as writeSyncReal } from 'node:fs'

// P-07 ── a state file is checked field by field ─────────────────────────────────

test('P-07: damaged state fields are corrupt, not coerced', () => {
  const good = () => JSON.parse(JSON.stringify(freshState())) as Record<string, any>
  const k = JSON.stringify(['co1', 'p1'])
  const withHistory = () => {
    const s = good()
    s.client.epoch = 1
    s.client.generations[k] = { generation: 5, digest: 'a'.repeat(64) }
    return s
  }
  assert.ok(cleanState(withHistory()), 'a valid state is accepted')
  const bad: [string, (s: Record<string, any>) => void][] = [
    ['negative epoch', (s) => { s.client.epoch = -1 }],
    ['negative crl number', (s) => { s.client.crl_number = -1 }],
    ['unsafe integer', (s) => { s.client.last_seen = 2 ** 60 }],
    ['float epoch', (s) => { s.client.epoch = 1.5 }],
    ['generation not an int', (s) => { s.client.generations[k].generation = 'not-an-int' }],
    ['generation zero', (s) => { s.client.generations[k].generation = 0 }],
    ['digest number', (s) => { s.client.generations[k].digest = 0 }],
    ['digest not hex', (s) => { s.client.generations[k].digest = 'z'.repeat(64) }],
    ['bad binding key', (s) => { s.client.generations['co1:p1'] = s.client.generations[k]; delete s.client.generations[k] }],
    ['revoked number', (s) => { s.client.revoked = [42] }],
    ['revoked not hex', (s) => { s.client.revoked = ['nope'] }],
    ['revoked repeated', (s) => { s.client.revoked = ['a'.repeat(32), 'a'.repeat(32)] }],
    ['signing kid garbage', (s) => { s.client.signing_kid = 'x' }],
    ['crl digest garbage', (s) => { s.client.crl_digest = 'x' }],
    ['identity ids', (s) => { s.identity = { company_id: 'a b', person_id: 'p1' } }],
    ['identity missing person', (s) => { s.identity = { company_id: 'co1' } }],
    ['installed digest', (s) => { s.installed = { generation: 1, epoch: 1, content_digest: 'x' } }],
    ['installed generation', (s) => { s.installed = { generation: -3, epoch: 1, content_digest: 'a'.repeat(64) } }],
    ['client array', (s) => { s.client = [] }],
    ['generations array', (s) => { s.client.generations = [] }],
    ['wrong version', (s) => { s.v = 2 }],
  ]
  for (const [name, mutate] of bad) {
    const s = withHistory()
    mutate(s)
    assert.equal(cleanState(s), null, name)
  }
})

test('P-07: damaged history cannot weaken rollback protection', async () => {
  const { w, stateDir, opts } = setup()
  w.generation = 4
  await syncWorkspace(opts())
  const f = join(stateDir, 'state.json')
  const s = JSON.parse(rf(f, 'utf8'))
  const key = Object.keys(s.client.generations)[0]!
  s.client.generations[key].generation = 'x'
  wf(f, JSON.stringify(s), { mode: 0o600 })
  w.forceGeneration = 2
  assert.equal(await code(syncWorkspace(opts())), 'state_corrupt')
})

test('P-07: a malformed managed record is refused before anything is deleted', async () => {
  const { appHome, opts } = setup()
  await syncWorkspace(opts())
  const f = join(appHome, '.3pa-managed.json')
  for (const bad of [{ v: 1, layout: { name: '../x', sha256: 'a'.repeat(64) }, mods: {} }, { v: 1, layout: null, mods: { m: { version: '1', files: {} } } }, { v: 1, layout: null, mods: { m: { version: '1.0.0', files: { '../../etc/passwd': 'a'.repeat(64) } } } }]) {
    wf(f, JSON.stringify(bad))
    assert.equal(await code(syncWorkspace(opts())), 'managed_record_invalid')
  }
  assert.ok(ex(join(appHome, 'mods', 'finance-dashboard')))
})

// P-08 ── the platform URL ───────────────────────────────────────────────────────

test('P-08: http is accepted only for the real loopback host names', () => {
  for (const ok of ['https://platform.example.test', 'https://platform.example.test/base/', 'http://localhost:8000', 'http://127.0.0.1:9000/x']) {
    assert.doesNotThrow(() => checkBaseUrl(ok), ok)
  }
  for (const bad of ['http://localhost.example.invalid', 'http://localhost@evil.example', 'http://evil.example', 'ftp://x.example', 'localhost:8000', 'not a url', '']) {
    assert.throws(() => checkBaseUrl(bad), (e: ProvisionError) => /^base_url_/.test(e.code), bad)
  }
  for (const bad of ['https://user:pw@platform.example.test', 'https://platform.example.test/?a=1', 'https://platform.example.test/#frag']) {
    assert.throws(() => checkBaseUrl(bad), (e: ProvisionError) => e.code === 'base_url_invalid', bad)
  }
  assert.equal(checkBaseUrl('https://platform.example.test/base///'), 'https://platform.example.test/base')
})

test('P-08: the library itself refuses a lookalike host before sending the token anywhere', async () => {
  const { w, opts } = setup()
  assert.equal(await code(syncWorkspace(opts({ baseUrl: 'http://localhost.example.invalid' }))), 'base_url_insecure')
  assert.equal(w.calls.length, 0)
})

// P-09 ── sign-in requests never follow a redirect ───────────────────────────────

test('P-09: the sign-in helper sends its credentials with redirect:error', async () => {
  const real = globalThis.fetch
  const seen: RequestInit[] = []
  globalThis.fetch = (async (_u: unknown, init?: RequestInit) => {
    seen.push(init ?? {})
    return new Response(JSON.stringify({ access_token: 'jwt' }), { status: 200 })
  }) as typeof fetch
  try {
    assert.equal(await webSignIn('https://platform.example.test', ['--oidc', 'id-token']), 'jwt')
  } finally {
    globalThis.fetch = real
  }
  assert.equal(seen.length, 1)
  assert.equal(seen[0]!.redirect, 'error')
})

// P-10 ── links are never trusted, even to identical bytes ───────────────────────

test('P-10: a managed file replaced by a link to identical bytes is drift and gets repaired', async () => {
  const { appHome, base, opts } = setup()
  await syncWorkspace(opts())
  const real = join(appHome, 'mods', 'finance-dashboard', 'main.js')
  const outside = join(base, 'outside.js')
  wf(outside, rf(real))
  rm(real)
  sl(outside, real)
  assert.deepEqual(scanDrift(appHome).modified, ['mods/finance-dashboard/main.js'])
  const r = await syncWorkspace(opts())
  assert.equal(r.status, 'updated')
  assert.ok(ls(real).isFile() && !ls(real).isSymbolicLink())
  assert.equal(read(outside), 'export default 1;\n') // the outside file was only a link target
})

test('P-10: a dangling link where a mod would go is refused, not replaced', async () => {
  const { appHome, base, opts } = setup()
  mk(join(appHome, 'mods'), { recursive: true })
  sl(join(base, 'nowhere'), join(appHome, 'mods', 'finance-dashboard'))
  assert.equal(await code(syncWorkspace(opts({ adopt: true }))), 'app_home_unsafe')
})

// P-11 ── one content, one size ──────────────────────────────────────────────────

test('P-11: the same content listed with two sizes is refused before downloading', async () => {
  const { w, appHome, opts } = setup()
  w.content = { layout: 'same', mods: { 'finance-dashboard': { 'a.js': 'same' } } }
  w.mutate = (p) => { ((p.mods as any)[0].files[0] as any).size = 999 }
  assert.equal(await code(syncWorkspace(opts())), 'size_conflict')
  assert.ok(!ex(join(appHome, 'layouts', 'finance-v2.json')))
  assert.ok(!w.calls.some((c) => c.startsWith('/me/workspace/files/')))
})

// P-12 ── error codes carry no server-controlled text ────────────────────────────

test('P-12: a server reason with unexpected characters is not echoed', async () => {
  const { w, opts } = setup()
  w.failManifest = new Response(JSON.stringify({ detail: { error: 'workspace_unavailable', reason: 'Bad Value <b>' } }), { status: 503 })
  assert.equal(await code(syncWorkspace(opts())), 'server_workspace_unavailable')
  w.failManifest = new Response(JSON.stringify({ detail: { reason: 'x'.repeat(200) } }), { status: 503 })
  assert.equal(await code(syncWorkspace(opts())), 'http_503')
  w.failManifest = new Response('<html>nope</html>', { status: 502 })
  assert.equal(await code(syncWorkspace(opts())), 'http_502')
})

// re-enroll ──────────────────────────────────────────────────────────────────────

test('re-enroll: a failed attempt leaves the existing state exactly where it was', async () => {
  const { w, stateDir, opts } = setup()
  await syncWorkspace(opts())
  const before = rf(join(stateDir, 'state.json'), 'utf8')
  w.failManifest = new Response('{}', { status: 503 })
  assert.equal(await code(syncWorkspace(opts({ reEnroll: true }))), 'http_503')
  assert.equal(rf(join(stateDir, 'state.json'), 'utf8'), before)
  assert.ok(!rd(stateDir).some((n) => n.startsWith('state.json.replaced-')))
})
