/**
 * Workspace provisioner (ADR-0029, on top of ADR-0027 / ADR-0028).
 *
 * `syncWorkspace` asks the platform for this person's signed manifest, verifies it with
 * the pinned root key, downloads every file, checks size and SHA-256, and only then
 * puts the layout and mods into the managed Herdr app home. The order is the safety:
 *
 *   1. nothing is trusted before `verifyWire` accepts it;
 *   2. the accepted state (generation, epoch, revocation list, clock) is saved BEFORE any
 *      file is touched, and also when verification fails after a revocation list was
 *      taken, so a rejected manifest never loses a revocation;
 *   3. files are downloaded and checked into a fresh staging directory (created
 *      exclusively, never over an existing path);
 *   4. activation renames whole items into place; the previous version is kept aside
 *      until the end and put back if any step fails, so a failure leaves the old
 *      workspace exactly as it was.
 *
 * Only names the provisioner manages are ever replaced. A layout or mod that already
 * exists and is not in `.3pa-managed.json`, or whose name Herdr ships (those are
 * rewritten on every Herdr start), makes the whole sync stop before any change.
 *
 * Mods are unsandboxed code (Herdr docs/security.md): this module is what stands between
 * the server and the user's machine, which is why it checks the signature chain, every
 * hash, every path and refuses to follow links in the app home.
 */

import { createHash, randomBytes } from 'node:crypto'
import {
  closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, mkdtempSync,
  openSync, readFileSync, readdirSync, renameSync, rmSync, writeSync,
} from 'node:fs'
import { dirname, join, sep } from 'node:path'

import {
  type ClientState, type Expected, ManifestError, digest, parseWire, verifyFile, verifyManifest,
} from './workspace-manifest.js'
import {
  type WorkspaceState, ensurePrivateDir, freshState, loadState, saveState, withLock,
} from './workspace-state.js'

export const AUD = 'herdr-provisioner'
/** Herdr rewrites its own layouts and mods whole on every start (defaults/AGENTS.md). */
export const SHIPPED_LAYOUTS = new Set(['main', 'terminals', 'win98'])
export const SHIPPED_MODS = new Set([
  'agents', 'changes', 'confirm', 'files', 'help', 'machine-add', 'menu', 'new-menu', 'pane',
  'peek', 'picker', 'prompt', 'spaces', 'tabs', 'terminals-bar', 'terminals-pane', 'toast',
  'win98', 'workspace-chrome', 'workspace-status', 'worktree',
])
const MANAGED_FILE = '.3pa-managed.json'
const DEFAULT_MAX_FILE = 16 * 1024 * 1024
const MAX_MANIFEST_RESPONSE = 256 * 1024

export class ProvisionError extends Error {
  code: string
  constructor(code: string, message?: string) {
    super(message ?? code)
    this.code = code
  }
}

export interface FsOps {
  rename: (from: string, to: string) => void
}
const realFs: FsOps = { rename: renameSync }

export interface SyncOptions {
  baseUrl: string
  webToken: string
  companyId?: string
  rootPub: string
  appHome: string
  stateDir: string
  clientVersion: string
  /** Seconds since the epoch; injectable for tests. */
  now?: () => number
  fetchImpl?: typeof fetch
  /** Take over an existing layout/mod with a managed name (otherwise sync stops). */
  adopt?: boolean
  /** Forget the pinned identity and bootstrap again from the server's floors. */
  reEnroll?: boolean
  maxFileBytes?: number
  fsOps?: FsOps
}

export interface SyncResult {
  status: 'updated' | 'unchanged'
  generation: number
  epoch: number
  layout: string
  mods: string[]
}

interface Entry { path: string; sha256: string; size: number }
interface ManifestBody {
  generation: number
  epoch: number
  layout: { id: string; sha256: string; size: number }
  mods: { name: string; version: string; files: Entry[] }[]
}

interface Managed {
  v: 1
  layout: { name: string; sha256: string } | null
  mods: Record<string, { version: string; files: Record<string, string> }>
}

// ── app home ─────────────────────────────────────────────────────────────────

function realDir(path: string, create: boolean): void {
  if (!existsSync(path)) {
    if (!create) return
    mkdirSync(path, { recursive: true, mode: 0o700 })
  }
  const st = lstatSync(path)
  if (st.isSymbolicLink() || !st.isDirectory()) throw new ProvisionError('app_home_unsafe', `${path} must be a real directory`)
}

function checkAppHome(appHome: string): void {
  realDir(appHome, true)
  for (const sub of ['layouts', 'mods']) realDir(join(appHome, sub), false)
}

function readManaged(appHome: string): Managed {
  const file = join(appHome, MANAGED_FILE)
  if (!existsSync(file)) return { v: 1, layout: null, mods: {} }
  const st = lstatSync(file)
  if (st.isSymbolicLink() || !st.isFile()) throw new ProvisionError('managed_record_invalid')
  try {
    const m = JSON.parse(readFileSync(file, 'utf8')) as Managed
    if (m.v !== 1 || typeof m.mods !== 'object' || m.mods === null) throw new Error('shape')
    return m
  } catch {
    throw new ProvisionError('managed_record_invalid')
  }
}

function writeAtomic(path: string, text: string): void {
  const tmp = `${path}.${randomBytes(6).toString('hex')}.tmp`
  const fd = openSync(tmp, 'wx', 0o600)
  try {
    writeSync(fd, text)
    fsyncSync(fd)
  } finally {
    closeSync(fd)
  }
  renameSync(tmp, path)
}

/** Telemetry is on by default in Herdr releases (docs/security.md); turn it off before
 * the first launch, keeping every other setting. An unreadable settings.json is left
 * alone and reported: overwriting a person's settings is not ours to do. */
export function ensureTelemetryOff(appHome: string): void {
  const file = join(appHome, 'settings.json')
  let settings: Record<string, unknown> = {}
  if (existsSync(file)) {
    const st = lstatSync(file)
    if (st.isSymbolicLink() || !st.isFile()) throw new ProvisionError('settings_invalid')
    try {
      const parsed = JSON.parse(readFileSync(file, 'utf8'))
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('shape')
      settings = parsed
    } catch {
      throw new ProvisionError('settings_invalid', 'settings.json is not valid JSON; fix or remove it')
    }
    if (settings.telemetry === false) return
  }
  writeAtomic(file, JSON.stringify({ ...settings, telemetry: false }, null, 2))
}

// ── network ──────────────────────────────────────────────────────────────────

async function readLimited(res: Response, max: number): Promise<Uint8Array> {
  const declared = Number(res.headers.get('content-length') ?? '')
  if (Number.isFinite(declared) && declared > max) throw new ProvisionError('response_too_large')
  if (!res.body) return new Uint8Array(await res.arrayBuffer())
  const reader = res.body.getReader()
  const chunks: Uint8Array[] = []
  let total = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    total += value.length
    if (total > max) {
      await reader.cancel().catch(() => undefined)
      throw new ProvisionError('response_too_large')
    }
    chunks.push(value)
  }
  return Buffer.concat(chunks)
}

async function get(o: SyncOptions, path: string, max: number): Promise<{ status: number; body: Uint8Array }> {
  const f = o.fetchImpl ?? fetch
  const res = await f(`${o.baseUrl.replace(/\/+$/, '')}${path}`, {
    headers: { Authorization: `Bearer ${o.webToken}` },
    redirect: 'error', // never send the token somewhere else
  })
  return { status: res.status, body: await readLimited(res, max) }
}

function failureCode(body: Uint8Array, status: number): string {
  try {
    const d = (JSON.parse(Buffer.from(body).toString('utf8')) as { detail?: unknown }).detail
    if (typeof d === 'object' && d !== null) {
      const x = d as { error?: unknown; reason?: unknown }
      if (typeof x.reason === 'string') return `server_${x.reason}`
      if (typeof x.error === 'string') return `server_${x.error}`
    }
  } catch { /* not JSON */ }
  return `http_${status}`
}

// ── sync ─────────────────────────────────────────────────────────────────────

const contentDigest = (b: ManifestBody) => digest({ layout: b.layout, mods: b.mods })

function planFiles(b: ManifestBody): { sha256: string; size: number; target: string[] }[] {
  const plan = new Map<string, { sha256: string; size: number; target: string[] }>()
  const add = (e: { sha256: string; size: number }, target: string) => {
    const cur = plan.get(e.sha256)
    if (cur) cur.target.push(target)
    else plan.set(e.sha256, { sha256: e.sha256, size: e.size, target: [target] })
  }
  add(b.layout, join('layouts', `${b.layout.id}.json`))
  for (const m of b.mods) for (const f of m.files) add(f, join('mods', m.name, ...f.path.split('/')))
  return [...plan.values()]
}

function precheck(b: ManifestBody, appHome: string, managed: Managed, adopt: boolean): void {
  const claim = (kind: 'layout' | 'mod', name: string, path: string, isOurs: boolean) => {
    if ((kind === 'layout' ? SHIPPED_LAYOUTS : SHIPPED_MODS).has(name)) throw new ProvisionError('shipped_name', `${kind} ${name} is a Herdr built-in`)
    if (existsSync(path) && !isOurs && !adopt) throw new ProvisionError('unmanaged_exists', `${kind} ${name} already exists and is not managed (use --adopt)`)
    if (existsSync(path) && lstatSync(path).isSymbolicLink()) throw new ProvisionError('app_home_unsafe', `${path} is a link`)
  }
  claim('layout', b.layout.id, join(appHome, 'layouts', `${b.layout.id}.json`), managed.layout?.name === b.layout.id)
  for (const m of b.mods) claim('mod', m.name, join(appHome, 'mods', m.name), m.name in managed.mods)
}

async function stageFiles(o: SyncOptions, b: ManifestBody, staging: string): Promise<void> {
  const max = o.maxFileBytes ?? DEFAULT_MAX_FILE
  for (const item of planFiles(b)) {
    if (item.size > max) throw new ProvisionError('file_too_large')
    const res = await get(o, `/me/workspace/files/${item.sha256}${o.companyId ? `?company_id=${encodeURIComponent(o.companyId)}` : ''}`, item.size)
    if (res.status !== 200) throw new ProvisionError(failureCode(res.body, res.status))
    try {
      verifyFile(res.body, item)
    } catch (e) {
      if (e instanceof ManifestError) throw new ProvisionError(`file_${e.code}`)
      throw e
    }
    for (const rel of item.target) {
      const dest = join(staging, rel)
      if (!dest.startsWith(staging + sep)) throw new ProvisionError('path_escape')
      mkdirSync(dirname(dest), { recursive: true, mode: 0o700 })
      const fd = openSync(dest, 'wx', 0o600) // exclusive: a path collision aborts the sync
      try {
        writeSync(fd, res.body)
        fsyncSync(fd)
      } finally {
        closeSync(fd)
      }
    }
  }
}

/** Put the staged items into the app home as one transaction. Returns the trash dir. */
function activate(
  b: ManifestBody, appHome: string, staging: string, managed: Managed, fsOps: FsOps,
): { trash: string; next: Managed } {
  const trash = mkdtempSync(join(appHome, '.3pa-trash-'))
  const undo: (() => void)[] = []
  const move = (from: string, to: string) => {
    mkdirSync(dirname(to), { recursive: true, mode: 0o700 })
    fsOps.rename(from, to)
  }
  const swap = (liveRel: string, stagedRel: string | null, trashName: string) => {
    const live = join(appHome, liveRel)
    const aside = join(trash, trashName)
    if (existsSync(live)) {
      move(live, aside)
      undo.push(() => { rmSync(live, { recursive: true, force: true }); renameSync(aside, live) })
    } else if (stagedRel) {
      undo.push(() => rmSync(live, { recursive: true, force: true }))
    }
    if (stagedRel) move(join(staging, stagedRel), live)
  }
  try {
    for (const old of Object.keys(managed.mods)) {
      if (!b.mods.some((m) => m.name === old)) swap(join('mods', old), null, `mod-${old}`)
    }
    if (managed.layout && managed.layout.name !== b.layout.id) swap(join('layouts', `${managed.layout.name}.json`), null, `layout-${managed.layout.name}`)
    swap(join('layouts', `${b.layout.id}.json`), join('layouts', `${b.layout.id}.json`), `layout-${b.layout.id}`)
    for (const m of b.mods) swap(join('mods', m.name), join('mods', m.name), `mod-${m.name}`)
  } catch (e) {
    for (const u of undo.reverse()) {
      try { u() } catch { /* keep restoring the rest */ }
    }
    rmSync(trash, { recursive: true, force: true })
    throw new ProvisionError('activation_failed', e instanceof Error ? e.message : String(e))
  }
  const next: Managed = {
    v: 1,
    layout: { name: b.layout.id, sha256: b.layout.sha256 },
    mods: Object.fromEntries(
      b.mods.map((m) => [m.name, { version: m.version, files: Object.fromEntries(m.files.map((f) => [f.path, f.sha256])) }]),
    ),
  }
  return { trash, next }
}

const isId = (x: unknown): x is string => typeof x === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(x)
const isCount = (x: unknown): x is number => Number.isInteger(x) && (x as number) >= 0 && (x as number) <= Number.MAX_SAFE_INTEGER

export async function syncWorkspace(o: SyncOptions): Promise<SyncResult> {
  const now = o.now ?? (() => Math.floor(Date.now() / 1000))
  const fsOps = o.fsOps ?? realFs
  ensurePrivateDir(o.stateDir)
  checkAppHome(o.appHome)
  ensureTelemetryOff(o.appHome)

  return withLock(o.stateDir, async () => {
    let state: WorkspaceState
    if (o.reEnroll) {
      // The operator chose to start over: keep the old file aside (it may be evidence),
      // whether or not it was readable, and bootstrap from the server's floors.
      const old = join(o.stateDir, 'state.json')
      if (existsSync(old)) renameSync(old, join(o.stateDir, `state.json.replaced-${Date.now()}`))
      state = freshState()
    } else {
      state = loadState(o.stateDir) ?? freshState()
    }

    // 1. what the server says (untrusted until verified)
    const q = o.companyId ? `?company_id=${encodeURIComponent(o.companyId)}` : ''
    const crlRes = await get(o, '/me/workspace/crl', MAX_MANIFEST_RESPONSE).catch(() => null)
    const mres = await get(o, `/me/workspace${q}`, MAX_MANIFEST_RESPONSE)
    if (mres.status !== 200) throw new ProvisionError(failureCode(mres.body, mres.status))
    let reply: { manifest: unknown; bootstrap: Record<string, unknown>; identity: Record<string, unknown> }
    try {
      reply = parseWire(mres.body) as unknown as typeof reply
    } catch (e) {
      throw new ProvisionError(e instanceof ManifestError ? `reply_${e.code}` : 'reply_invalid')
    }
    let crl: unknown
    if (crlRes && crlRes.status === 200) {
      try { crl = parseWire(crlRes.body) } catch { crl = undefined }
    }

    // 2. who this machine is: pinned on first use, then compared every time
    const idn = reply.identity
    if (!idn || !isId(idn.company_id) || !isId(idn.person_id)) throw new ProvisionError('reply_invalid')
    if (state.identity && (state.identity.company_id !== idn.company_id || state.identity.person_id !== idn.person_id)) {
      throw new ProvisionError('identity_changed', 'the server answered for a different person; use --re-enroll if this is intended')
    }
    const identity = { company_id: idn.company_id, person_id: idn.person_id }
    const key = JSON.stringify([identity.company_id, identity.person_id])
    const hasHistory = state.client.epoch > 0 && key in state.client.generations
    const bs = reply.bootstrap ?? {}
    const expected: Expected = { ...identity, aud: AUD, client_version: o.clientVersion }
    if (!hasHistory) {
      if (!isCount(bs.min_generation) || !isCount(bs.min_epoch) || !isCount(bs.min_crl_number)) throw new ProvisionError('reply_invalid')
      expected.min_generation = bs.min_generation
      expected.min_epoch = bs.min_epoch
      expected.min_crl_number = bs.min_crl_number
    }

    // 3. verify; keep whatever state was reached even when the manifest is refused
    let payload: ManifestBody
    let client: ClientState
    try {
      const [p, c] = verifyManifest(reply.manifest, { rootPub: o.rootPub, expected, now: now(), state: state.client, crl })
      payload = p as unknown as ManifestBody
      client = c
    } catch (e) {
      if (e instanceof ManifestError) {
        if (e.state && JSON.stringify(e.state) !== JSON.stringify(state.client)) saveState(o.stateDir, { ...state, client: e.state })
        throw new ProvisionError(`manifest_${e.code}`)
      }
      throw e
    }

    // 4. accept: persisted BEFORE anything is installed
    const accepted: WorkspaceState = { ...state, identity, client }
    saveState(o.stateDir, accepted)

    // 5. nothing to install when the content is unchanged and intact
    const managed = readManaged(o.appHome)
    const cd = contentDigest(payload)
    if (state.installed?.content_digest === cd && intact(o.appHome).length === 0) {
      saveState(o.stateDir, { ...accepted, installed: { generation: payload.generation, epoch: payload.epoch, content_digest: cd } })
      return { status: 'unchanged' as const, generation: payload.generation, epoch: payload.epoch, layout: payload.layout.id, mods: payload.mods.map((m) => m.name) }
    }

    // 6. download and verify into staging; the live workspace is untouched until done
    precheck(payload, o.appHome, managed, o.adopt === true)
    const staging = mkdtempSync(join(o.appHome, '.3pa-staging-'))
    let trash: string | undefined
    try {
      await stageFiles(o, payload, staging)
      const done = activate(payload, o.appHome, staging, managed, fsOps)
      trash = done.trash
      writeAtomic(join(o.appHome, MANAGED_FILE), JSON.stringify(done.next, null, 2))
    } catch (e) {
      rmSync(staging, { recursive: true, force: true })
      throw e
    }
    rmSync(staging, { recursive: true, force: true })
    if (trash) rmSync(trash, { recursive: true, force: true })
    saveState(o.stateDir, { ...accepted, installed: { generation: payload.generation, epoch: payload.epoch, content_digest: cd } })
    return { status: 'updated' as const, generation: payload.generation, epoch: payload.epoch, layout: payload.layout.id, mods: payload.mods.map((m) => m.name) }
  })
}

// ── drift ────────────────────────────────────────────────────────────────────

export interface Drift {
  missing: string[]
  modified: string[]
  /** Mods in the app home that are neither managed nor shipped by Herdr. */
  unmanagedMods: string[]
  /** Files inside a managed mod that the manifest does not list. */
  extraFiles: string[]
}

const sha = (buf: Uint8Array) => createHash('sha256').update(buf).digest('hex')

function walk(dir: string, base = ''): string[] {
  const out: string[] = []
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const rel = base ? `${base}/${e.name}` : e.name
    if (e.isDirectory()) out.push(...walk(join(dir, e.name), rel))
    else out.push(rel)
  }
  return out
}

/** Compare the app home with what was installed. A diagnostic, not proof: the same user
 * can edit the record too (ADR-0026 decision 4). */
export function scanDrift(appHome: string): Drift {
  const managed = readManaged(appHome)
  const d: Drift = { missing: [], modified: [], unmanagedMods: [], extraFiles: [] }
  if (managed.layout) {
    const f = join(appHome, 'layouts', `${managed.layout.name}.json`)
    if (!existsSync(f)) d.missing.push(`layouts/${managed.layout.name}.json`)
    else if (sha(readFileSync(f)) !== managed.layout.sha256) d.modified.push(`layouts/${managed.layout.name}.json`)
  }
  for (const [name, m] of Object.entries(managed.mods)) {
    const root = join(appHome, 'mods', name)
    if (!existsSync(root)) {
      d.missing.push(`mods/${name}`)
      continue
    }
    const present = new Set(walk(root))
    for (const [path, hash] of Object.entries(m.files)) {
      if (!present.has(path)) d.missing.push(`mods/${name}/${path}`)
      else if (sha(readFileSync(join(root, path))) !== hash) d.modified.push(`mods/${name}/${path}`)
      present.delete(path)
    }
    for (const extra of present) d.extraFiles.push(`mods/${name}/${extra}`)
  }
  const modsDir = join(appHome, 'mods')
  if (existsSync(modsDir)) {
    for (const e of readdirSync(modsDir, { withFileTypes: true })) {
      if (e.name.startsWith('.') || SHIPPED_MODS.has(e.name) || e.name in managed.mods) continue
      d.unmanagedMods.push(e.name)
    }
  }
  return d
}

function intact(appHome: string): string[] {
  const d = scanDrift(appHome)
  return [...d.missing, ...d.modified, ...d.extraFiles]
}

