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

import { ProvisionError, SHIPPED_MODS, ensureTelemetryOff, scanDrift, syncWorkspace } from '../src/utils/provisioner.ts'
import { canonicalBytes, keyId } from '../src/utils/workspace-manifest.ts'
import { loadState, saveState, withLock, freshState, StateError } from '../src/utils/workspace-state.ts'

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
    return { cert: this.cert(), payload, sig: signDoc(this.signing.priv, 'manifest', payload) }
  }

  fetchImpl: typeof fetch = async (url) => {
    const u = new URL(String(url))
    this.calls.push(u.pathname)
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
    if (u.pathname === '/me/workspace/crl') return this.crl ? json(200, this.crl) : json(404, { detail: 'none' })
    if (u.pathname === '/me/workspace') {
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
  assert.deepEqual(scanDrift(appHome), { missing: [], modified: [], unmanagedMods: [], extraFiles: [] })
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
  })
})
