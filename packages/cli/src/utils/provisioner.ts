/**
 * Workspace provisioner (ADR-0029, on top of ADR-0027 / ADR-0028).
 *
 * `syncWorkspace` asks the platform for this person's signed manifest, verifies it with
 * the pinned root key, downloads every file, checks size and SHA-256, and only then
 * puts the layout and mods into the managed Herdr app home. The order is the safety:
 *
 *   1. a revocation list is taken first and saved, so a refused or unavailable manifest
 *      never costs a revocation;
 *   2. nothing in the manifest is trusted before `verifyManifest` accepts it;
 *   3. the accepted state (generation, epoch, clock) is saved BEFORE any file is touched;
 *   4. files are downloaded and checked into a fresh staging directory (created
 *      exclusively, never over an existing path, every byte written and measured);
 *   5. activation is a journalled transaction: the plan is written to disk first, replaced
 *      items are moved aside (not deleted) and staged ones renamed in, then the managed
 *      record is written, and only deleting the journal commits. Any failure - or a crash,
 *      found on the next start - rolls everything back to the previous workspace. If a
 *      rollback itself cannot finish, the saved items are kept and the sync stops with
 *      `recovery_required`; nothing is ever deleted on a failed rollback.
 *
 * Only names the provisioner manages are ever replaced. A layout or mod that already
 * exists and is not in `.3pa-managed.json`, or whose name Herdr ships (those are
 * rewritten on every Herdr start), makes the whole sync stop before any change.
 *
 * Mods are unsandboxed code (Herdr docs/security.md): this module is what stands between
 * the server and the user's machine, which is why it checks the signature chain, every
 * hash, every path and refuses to follow links in the app home.
 */

import { createHash } from 'node:crypto'
import {
  constants as fsConstants, copyFileSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync,
} from 'node:fs'
import { dirname, join, resolve, sep } from 'node:path'

import { FsError, createFileExclusive, fsyncDir, lexists, writeFileAtomic } from './fsutil.js'
import {
  type ClientState, type Expected, ManifestError, digest, parseWire, verifyCrl, verifyFile, verifyManifest,
} from './workspace-manifest.js'
import {
  StateError, type WorkspaceState, ensurePrivateDir, freshState, hasHistoryFor, loadState, saveState, withLock,
} from './workspace-state.js'

export const AUD = 'herdr-provisioner'
/** Herdr rewrites its own layouts and mods whole on every start (defaults/AGENTS.md). */
export const SHIPPED_LAYOUTS = new Set(['main', 'terminals', 'win98'])
export const SHIPPED_MODS = new Set([
  'agents', 'changes', 'confirm', 'files', 'help', 'machine-add', 'menu', 'new-menu', 'pane',
  'peek', 'picker', 'prompt', 'spaces', 'tabs', 'terminals-bar', 'terminals-pane', 'toast',
  'win98', 'workspace-chrome', 'workspace-status', 'worktree',
])
/** Test seam: runs after each staged file has been written. */
export const provisionHooks: { afterStageWrite?: () => void } = {}

const MANAGED_FILE = '.3pa-managed.json'
const JOURNAL_FILE = '.3pa-journal.json'
const DEFAULT_MAX_FILE = 16 * 1024 * 1024
const MAX_RESPONSE = 256 * 1024
const SYNC_MAX_MS = 20 * 60 * 1000
const REQUEST_MAX_MS = 60 * 1000

const own = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k)
const HEX64 = /^[0-9a-f]{64}$/
const NAME = /^[a-z0-9][a-z0-9._-]{0,63}$/
const VERSION = /^[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$/
const REL_PATH = /^[A-Za-z0-9._@+-]{1,255}(\/[A-Za-z0-9._@+-]{1,255})*$/
const ID = /^[A-Za-z0-9_-]{1,64}$/
/** A relative path of ASCII components, none of which is `.` or `..`. */
const validRel = (p: string) => REL_PATH.test(p) && p.split('/').every((c) => c !== '.' && c !== '..')

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
  /** The whole sync is cut off after this long (default 20 minutes, far below the age at
   * which a lock counts as stale), and each request after one minute. */
  maxDurationMs?: number
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

// ── base URL ─────────────────────────────────────────────────────────────────

/** `https://` anywhere, `http://` only for the loopback host names. Credentials, query and
 * fragment are refused. Returns the URL without a trailing slash. */
export function checkBaseUrl(raw: string): string {
  let u: URL
  try {
    u = new URL(raw)
  } catch {
    throw new ProvisionError('base_url_invalid', 'the platform URL is not a valid URL')
  }
  const loopback = u.hostname === 'localhost' || u.hostname === '127.0.0.1' || u.hostname === '[::1]'
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && loopback)) {
    throw new ProvisionError('base_url_insecure', 'the platform URL must be https:// (http:// only for localhost)')
  }
  if (u.username || u.password || u.search || u.hash || !u.hostname) {
    throw new ProvisionError('base_url_invalid', 'the platform URL must not contain credentials, a query or a fragment')
  }
  return u.origin + u.pathname.replace(/\/+$/, '')
}

// ── app home ─────────────────────────────────────────────────────────────────

function realDir(path: string, create: boolean): void {
  if (!lexists(path)) {
    if (!create) return
    mkdirSync(path, { recursive: true, mode: 0o700 })
  }
  const st = lstatSync(path)
  if (st.isSymbolicLink() || !st.isDirectory()) throw new ProvisionError('app_home_unsafe', 'the Herdr app home contains a link or file where a folder is expected')
}

function checkAppHome(appHome: string): void {
  realDir(appHome, true)
  for (const sub of ['layouts', 'mods']) realDir(join(appHome, sub), false)
}

/** The managed record, checked field by field; anything odd is an error, not a guess. */
export function cleanManaged(x: unknown): Managed | null {
  if (typeof x !== 'object' || x === null || (x as { v?: unknown }).v !== 1) return null
  const m = x as { layout?: unknown; mods?: unknown }
  let layout: Managed['layout'] = null
  if (m.layout !== null && m.layout !== undefined) {
    const l = m.layout as { name?: unknown; sha256?: unknown }
    if (typeof l !== 'object' || typeof l.name !== 'string' || !NAME.test(l.name) || typeof l.sha256 !== 'string' || !HEX64.test(l.sha256)) return null
    layout = { name: l.name, sha256: l.sha256 }
  }
  if (typeof m.mods !== 'object' || m.mods === null || Array.isArray(m.mods)) return null
  const mods: Managed['mods'] = Object.create(null)
  for (const name of Object.keys(m.mods)) {
    const e = (m.mods as Record<string, { version?: unknown; files?: unknown }>)[name]!
    if (!NAME.test(name) || typeof e !== 'object' || e === null || typeof e.version !== 'string' || !VERSION.test(e.version)) return null
    if (typeof e.files !== 'object' || e.files === null || Array.isArray(e.files)) return null
    const files: Record<string, string> = Object.create(null)
    for (const p of Object.keys(e.files)) {
      const h = (e.files as Record<string, unknown>)[p]
      if (!validRel(p) || typeof h !== 'string' || !HEX64.test(h)) return null
      files[p] = h
    }
    mods[name] = { version: e.version, files }
  }
  return { v: 1, layout, mods }
}

function readManaged(appHome: string): Managed {
  const file = join(appHome, MANAGED_FILE)
  if (!lexists(file)) return { v: 1, layout: null, mods: Object.create(null) }
  const st = lstatSync(file)
  if (st.isSymbolicLink() || !st.isFile()) throw new ProvisionError('managed_record_invalid')
  let parsed: unknown
  try {
    parsed = JSON.parse(readFileSync(file, 'utf8'))
  } catch {
    throw new ProvisionError('managed_record_invalid')
  }
  const m = cleanManaged(parsed)
  if (!m) throw new ProvisionError('managed_record_invalid')
  return m
}

/** Telemetry is on by default in Herdr releases (docs/security.md); turn it off before
 * the first launch, keeping every other setting. An unreadable settings.json is left
 * alone and reported: overwriting a person's settings is not ours to do. This runs before
 * the manifest is verified on purpose (a first launch must not report), and it touches
 * nothing else. */
export function ensureTelemetryOff(appHome: string): void {
  const file = join(appHome, 'settings.json')
  let settings: Record<string, unknown> = {}
  if (lexists(file)) {
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
  writeFileAtomic(file, JSON.stringify({ ...settings, telemetry: false }, null, 2))
}

// ── network ──────────────────────────────────────────────────────────────────

async function readLimited(res: Response, max: number): Promise<Uint8Array> {
  const declared = Number(res.headers.get('content-length') ?? '')
  if (Number.isFinite(declared) && declared > max) throw new ProvisionError('response_too_large')
  if (!res.body) {
    const all = new Uint8Array(await res.arrayBuffer())
    if (all.length > max) throw new ProvisionError('response_too_large')
    return all
  }
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

async function get(o: SyncOptions, base: string, path: string, max: number): Promise<{ status: number; body: Uint8Array }> {
  const f = o.fetchImpl ?? fetch
  const left = deadlines.get(o) !== undefined ? deadlines.get(o)! - Date.now() : REQUEST_MAX_MS
  if (left <= 0) throw new ProvisionError('sync_timeout', 'the sync took too long and was stopped; no new update was applied')
  let res: Response
  try {
    res = await f(`${base}${path}`, {
      headers: { Authorization: `Bearer ${o.webToken}` },
      redirect: 'error', // never send the token somewhere else
      signal: AbortSignal.timeout(Math.min(REQUEST_MAX_MS, left)),
    })
    return { status: res.status, body: await readLimited(res, max) }
  } catch (e) {
    if ((e as Error)?.name === 'TimeoutError' || (e as Error)?.name === 'AbortError') {
      throw new ProvisionError('sync_timeout', 'the platform did not answer in time; no new update was applied')
    }
    throw e
  }
}

/** When each sync must be finished by (a stale lock is only taken after an hour). */
const deadlines = new WeakMap<SyncOptions, number>()

/** Cooperative: checked between steps, before anything irreversible. A blocked disk call
 * cannot be interrupted from JavaScript, so this is a soft bound, not a watchdog. */
function assertTime(o: SyncOptions): void {
  const d = deadlines.get(o)
  if (d !== undefined && Date.now() > d) throw new ProvisionError('sync_timeout', 'the sync took too long and was stopped; no new update was applied')
}

/** A short, value-free code. Whatever the server sends is reduced to a fixed alphabet. */
function failureCode(body: Uint8Array, status: number): string {
  try {
    const d = (JSON.parse(Buffer.from(body).toString('utf8')) as { detail?: unknown }).detail
    if (typeof d === 'object' && d !== null) {
      const x = d as { error?: unknown; reason?: unknown }
      for (const v of [x.reason, x.error]) {
        if (typeof v === 'string' && /^[a-z0-9_]{1,48}$/.test(v)) return `server_${v}`
      }
    }
  } catch { /* not JSON */ }
  return `http_${status}`
}

// ── plan and staging ─────────────────────────────────────────────────────────

const contentDigest = (b: ManifestBody) => digest({ layout: b.layout, mods: b.mods })

function planFiles(b: ManifestBody): { sha256: string; size: number; target: string[] }[] {
  const plan = new Map<string, { sha256: string; size: number; target: string[] }>()
  const add = (e: { sha256: string; size: number }, target: string) => {
    const cur = plan.get(e.sha256)
    if (cur) {
      if (cur.size !== e.size) throw new ProvisionError('size_conflict', 'the manifest gives one content two sizes')
      cur.target.push(target)
    } else plan.set(e.sha256, { sha256: e.sha256, size: e.size, target: [target] })
  }
  add(b.layout, join('layouts', `${b.layout.id}.json`))
  for (const m of b.mods) for (const f of m.files) add(f, join('mods', m.name, ...f.path.split('/')))
  return [...plan.values()]
}

function precheck(b: ManifestBody, appHome: string, managed: Managed, adopt: boolean): void {
  const claim = (kind: 'layout' | 'mod', name: string, path: string, isOurs: boolean) => {
    if ((kind === 'layout' ? SHIPPED_LAYOUTS : SHIPPED_MODS).has(name)) throw new ProvisionError('shipped_name', `${kind} ${name} is a Herdr built-in`)
    if (!lexists(path)) return
    if (lstatSync(path).isSymbolicLink()) throw new ProvisionError('app_home_unsafe', `${path} is a link`)
    if (!isOurs && !adopt) throw new ProvisionError('unmanaged_exists', `${kind} ${name} already exists and is not managed (use --adopt)`)
  }
  claim('layout', b.layout.id, join(appHome, 'layouts', `${b.layout.id}.json`), managed.layout?.name === b.layout.id)
  for (const m of b.mods) claim('mod', m.name, join(appHome, 'mods', m.name), own(managed.mods, m.name))
}

async function stageFiles(o: SyncOptions, base: string, b: ManifestBody, staging: string): Promise<void> {
  const max = o.maxFileBytes ?? DEFAULT_MAX_FILE
  const q = o.companyId ? `?company_id=${encodeURIComponent(o.companyId)}` : ''
  for (const item of planFiles(b)) {
    if (item.size > max) throw new ProvisionError('file_too_large')
    const res = await get(o, base, `/me/workspace/files/${item.sha256}${q}`, item.size)
    if (res.status !== 200) throw new ProvisionError(failureCode(res.body, res.status))
    try {
      verifyFile(res.body, item)
    } catch (e) {
      if (e instanceof ManifestError) throw new ProvisionError(`file_${e.code}`)
      throw e
    }
    for (const rel of item.target) {
      assertTime(o)
      const dest = join(staging, rel)
      if (!dest.startsWith(staging + sep)) throw new ProvisionError('path_escape')
      mkdirSync(dirname(dest), { recursive: true, mode: 0o700 })
      try {
        createFileExclusive(dest, res.body) // exclusive, fully written, size checked
        provisionHooks.afterStageWrite?.()
      } catch (e) {
        throw new ProvisionError(e instanceof FsError ? e.code : 'stage_write_failed')
      }
    }
  }
}

// ── journalled activation ────────────────────────────────────────────────────

interface Op {
  /** Path below the app home: `layouts/<name>.json` or `mods/<name>`. */
  live: string
  hadLive: boolean
  /** Where the previous item was put (inside the trash directory), if there was one. */
  aside: string | null
  /** Where the new item waits in staging, if there is one. */
  staged: string | null
}
interface Journal {
  v: 1
  trash: string
  staging: string
  ops: Op[]
  prevManaged: Managed | null
}

const LIVE_PATH = /^(layouts\/[a-z0-9][a-z0-9._-]{0,63}\.json|mods\/[a-z0-9][a-z0-9._-]{0,63})$/

/** `p` is a direct child of the app home whose name starts with `prefix`, and is a real
 * folder (never a link) or not there at all. */
function realChild(appHome: string, p: string, prefix: string): boolean {
  const home = resolve(appHome)
  const abs = resolve(p)
  if (dirname(abs) !== home || !abs.slice(home.length + 1).startsWith(prefix)) return false
  if (!lexists(abs)) return true
  const st = lstatSync(abs)
  return st.isDirectory() && !st.isSymbolicLink()
}

/** The name an old item is given inside the trash folder (the same rule as `plan()`). */
function trashTag(live: string): string {
  return live.startsWith('mods/') ? `mod-${live.slice(5)}` : `layout-${live.slice(8, -5)}`
}

/** Put everything an interrupted or failed activation moved back where it was. Idempotent;
 * returns the number of steps that could not be undone (0 means fully restored). */
function undoOps(appHome: string, ops: Op[], fsOps: FsOps): number {
  let failures = 0
  for (const op of [...ops].reverse()) {
    const live = join(appHome, op.live)
    try {
      if (op.hadLive) {
        if (op.aside !== null && lexists(op.aside)) {
          rmSync(live, { recursive: true, force: true })
          mkdirSync(dirname(live), { recursive: true, mode: 0o700 })
          fsOps.rename(op.aside, live)
        } // else the original was never moved: it is still in place
      } else if (op.staged === null || !lexists(op.staged)) {
        rmSync(live, { recursive: true, force: true }) // we created it (the staged copy is gone)
      }
    } catch {
      failures++
    }
  }
  return failures
}

function writeManagedRecord(appHome: string, m: Managed | null, fsOps: FsOps = realFs): void {
  const file = join(appHome, MANAGED_FILE)
  if (m === null) rmSync(file, { force: true })
  else writeFileAtomic(file, JSON.stringify(m, null, 2), 0o600, fsOps.rename)
}

function readJournal(appHome: string): Journal | null {
  const file = join(appHome, JOURNAL_FILE)
  if (!lexists(file)) return null
  const bad = () => new ProvisionError('recovery_required', `${JOURNAL_FILE} in the app home is damaged; the previous items are kept in the .3pa-trash-* folder`)
  let j: Journal
  try {
    j = JSON.parse(readFileSync(file, 'utf8')) as Journal
  } catch {
    throw bad()
  }
  if (j?.v !== 1 || !Array.isArray(j.ops) || typeof j.trash !== 'string' || typeof j.staging !== 'string') throw bad()
  if (!realChild(appHome, j.trash, '.3pa-trash-') || !realChild(appHome, j.staging, '.3pa-staging-')) throw bad()
  const seen = new Set<string>()
  for (const op of j.ops) {
    if (typeof op?.live !== 'string' || !LIVE_PATH.test(op.live) || typeof op.hadLive !== 'boolean' || seen.has(op.live)) throw bad()
    seen.add(op.live)
    // Exactly what activate() writes: an old item has a fixed place in the trash, a new one a
    // fixed place in staging, and nothing else is acted on. A journal that says otherwise is
    // refused before anything is moved or deleted.
    const wantAside = op.hadLive ? join(j.trash, trashTag(op.live)) : null
    if (op.aside !== wantAside) throw bad()
    if (op.staged !== null && op.staged !== join(j.staging, op.live)) throw bad()
  }
  if (j.prevManaged !== null && !cleanManaged(j.prevManaged)) throw bad()
  return j
}

/** A previous run died (or could not roll back) in the middle of an activation: finish
 * the rollback now, before anything else, so the app home is exactly as it was. */
const TMP_LEFTOVER = /^(\.3pa-managed\.json|settings\.json)\.[0-9a-f]{12}\.tmp$/

function sweepTempFiles(appHome: string): void {
  for (const e of readdirSync(appHome, { withFileTypes: true })) {
    if (e.isFile() && TMP_LEFTOVER.test(e.name)) rmSync(join(appHome, e.name), { force: true })
  }
}

export function recoverInterrupted(appHomeIn: string, fsOps: FsOps = realFs): boolean {
  const appHome = resolve(appHomeIn)
  sweepTempFiles(appHome) // a crash can leave a half-written temp file next to a file we replace
  const j = readJournal(appHome)
  if (!j) return false
  if (undoOps(appHome, j.ops, fsOps) > 0) {
    throw new ProvisionError('recovery_required', `an earlier sync was interrupted and could not be rolled back; the previous items are in ${j.trash}`)
  }
  writeManagedRecord(appHome, j.prevManaged === null ? null : cleanManaged(j.prevManaged), fsOps)
  rmSync(j.staging, { recursive: true, force: true })
  rmSync(j.trash, { recursive: true, force: true })
  rmSync(join(appHome, JOURNAL_FILE), { force: true })
  fsyncDir(appHome)
  return true
}

function activate(
  b: ManifestBody, appHome: string, staging: string, managed: Managed, hadManagedFile: boolean, fsOps: FsOps,
): void {
  const trash = mkdtempSync(join(appHome, '.3pa-trash-'))
  const ops: Op[] = []
  const plan = (liveRel: string, stagedRel: string | null, tag: string) => {
    const hadLive = lexists(join(appHome, liveRel))
    ops.push({ live: liveRel, hadLive, aside: hadLive ? join(trash, tag) : null, staged: stagedRel ? join(staging, stagedRel) : null })
  }
  for (const old of Object.keys(managed.mods)) {
    if (!b.mods.some((m) => m.name === old)) plan(join('mods', old), null, `mod-${old}`)
  }
  if (managed.layout && managed.layout.name !== b.layout.id) plan(join('layouts', `${managed.layout.name}.json`), null, `layout-${managed.layout.name}`)
  plan(join('layouts', `${b.layout.id}.json`), join('layouts', `${b.layout.id}.json`), `layout-${b.layout.id}`)
  for (const m of b.mods) plan(join('mods', m.name), join('mods', m.name), `mod-${m.name}`)

  const journal: Journal = { v: 1, trash, staging, ops, prevManaged: hadManagedFile ? managed : null }
  writeFileAtomic(join(appHome, JOURNAL_FILE), JSON.stringify(journal, null, 2)) // durable before the first rename

  const next: Managed = {
    v: 1,
    layout: { name: b.layout.id, sha256: b.layout.sha256 },
    mods: Object.fromEntries(
      b.mods.map((m) => [m.name, { version: m.version, files: Object.fromEntries(m.files.map((f) => [f.path, f.sha256])) }]),
    ),
  }
  try {
    for (const op of ops) {
      const live = join(appHome, op.live)
      if (op.hadLive && op.aside) fsOps.rename(live, op.aside)
      if (op.staged) {
        mkdirSync(dirname(live), { recursive: true, mode: 0o700 })
        fsOps.rename(op.staged, live)
      }
    }
    writeManagedRecord(appHome, next, fsOps)
  } catch (e) {
    const errno = (e as NodeJS.ErrnoException).code
    if (undoOps(appHome, ops, fsOps) > 0) {
      // Keep the journal and the saved items: the next run (or the operator) finishes it.
      throw new ProvisionError('recovery_required', `the update failed and could not be rolled back completely; the previous items are in ${trash}`)
    }
    try { writeManagedRecord(appHome, hadManagedFile ? managed : null, realFs) } catch { /* the live items are back; the old record is still what it was */ }
    rmSync(trash, { recursive: true, force: true })
    rmSync(join(appHome, JOURNAL_FILE), { force: true })
    const detail = typeof errno === 'string' && /^E[A-Z0-9]+$/.test(errno) ? ` (${errno})` : ''
    throw new ProvisionError('activation_failed', `the update could not be applied${detail}; the previous workspace was restored`)
  }
  rmSync(join(appHome, JOURNAL_FILE), { force: true }) // the commit point
  fsyncDir(appHome)
  rmSync(trash, { recursive: true, force: true })
}

// ── sync ─────────────────────────────────────────────────────────────────────

const isId = (x: unknown): x is string => typeof x === 'string' && ID.test(x)
const isCount = (x: unknown): x is number => Number.isSafeInteger(x) && (x as number) >= 0

export async function syncWorkspace(opts: SyncOptions): Promise<SyncResult> {
  // Absolute paths, once: the journal and every later step must mean the same folder even if
  // the next run starts from another working directory.
  const o: SyncOptions = { ...opts, appHome: resolve(opts.appHome), stateDir: resolve(opts.stateDir) }
  if (o.maxDurationMs !== undefined && !(Number.isSafeInteger(o.maxDurationMs) && o.maxDurationMs > 0 && o.maxDurationMs <= SYNC_MAX_MS)) {
    // A longer budget would outlive the age at which another run may take the lock over.
    throw new ProvisionError('bad_duration', `maxDurationMs must be a whole number of milliseconds between 1 and ${SYNC_MAX_MS}`)
  }
  const now = o.now ?? (() => Math.floor(Date.now() / 1000))
  const fsOps = o.fsOps ?? realFs
  const base = checkBaseUrl(o.baseUrl)
  ensurePrivateDir(o.stateDir)
  checkAppHome(o.appHome)
  deadlines.set(o, Date.now() + (o.maxDurationMs ?? SYNC_MAX_MS))

  try {
    return await runSync(o, base, now, fsOps)
  } catch (e) {
    const errno = (e as NodeJS.ErrnoException)?.code
    if (!(e instanceof ProvisionError) && !(e instanceof StateError) && !(e instanceof ManifestError) && typeof errno === 'string' && /^E[A-Z0-9]+$/.test(errno)) {
      // A file operation failed unexpectedly (a disk error, a permission). Say so plainly;
      // nothing was deleted on the strength of a failed look.
      throw new ProvisionError('fs_error', `a file operation failed (${errno}); \`3pa workspace status\` shows where things stand, and running the sync again is safe`)
    }
    throw e
  }
}

async function runSync(o: SyncOptions, base: string, now: () => number, fsOps: FsOps): Promise<SyncResult> {
  return withLock(o.stateDir, async (assertOwned) => {
    // A crashed or half-rolled-back earlier run is finished first (while we hold the lock),
    // and so is the settings write: a temp file belongs to whoever holds the lock.
    assertOwned()
    recoverInterrupted(o.appHome, fsOps)
    ensureTelemetryOff(o.appHome)

    let state: WorkspaceState
    let replaceOld = false
    if (o.reEnroll) {
      // The operator chose to start over. The old file is only moved aside once the new
      // state is about to replace it, so a failed attempt leaves everything as it was.
      state = freshState()
      replaceOld = lexists(join(o.stateDir, 'state.json'))
    } else {
      state = loadState(o.stateDir) ?? freshState()
    }
    const persist = (s: WorkspaceState) => {
      assertOwned()
      if (replaceOld) {
        // Keep a copy of the old file, but leave it IN PLACE: the new state replaces it in one
        // atomic rename below, so a failed write cannot leave the machine with no state.
        copyFileSync(join(o.stateDir, 'state.json'), join(o.stateDir, `state.json.replaced-${Date.now()}`), fsConstants.COPYFILE_EXCL)
        replaceOld = false
      }
      saveState(o.stateDir, s)
    }

    // 1. A revocation list comes first and is kept whatever happens to the manifest.
    const crlRes = await get(o, base, '/me/workspace/crl', MAX_RESPONSE).catch(() => null)
    if (crlRes && crlRes.status === 200) {
      let ingested: ClientState
      try {
        ingested = verifyCrl(parseWire(crlRes.body), o.rootPub, state.client, now())
      } catch (e) {
        if (e instanceof ManifestError) {
          if (e.state && JSON.stringify(e.state) !== JSON.stringify(state.client)) persist({ ...state, client: e.state })
          throw new ProvisionError(`crl_${e.code}`)
        }
        throw e
      }
      if (JSON.stringify(ingested) !== JSON.stringify(state.client)) {
        state = { ...state, client: ingested }
        persist(state)
      }
    }

    // 2. What the server says (untrusted until verified).
    const q = o.companyId ? `?company_id=${encodeURIComponent(o.companyId)}` : ''
    const mres = await get(o, base, `/me/workspace${q}`, MAX_RESPONSE)
    if (mres.status !== 200) throw new ProvisionError(failureCode(mres.body, mres.status))
    let reply: { manifest: unknown; bootstrap: Record<string, unknown>; identity: Record<string, unknown> }
    try {
      reply = parseWire(mres.body) as unknown as typeof reply
    } catch (e) {
      throw new ProvisionError(e instanceof ManifestError ? `reply_${e.code}` : 'reply_invalid')
    }

    // 3. Who this machine is: pinned on first use, then compared every time.
    const idn = reply.identity
    if (!idn || !isId(idn.company_id) || !isId(idn.person_id)) throw new ProvisionError('reply_invalid')
    if (state.identity && (state.identity.company_id !== idn.company_id || state.identity.person_id !== idn.person_id)) {
      throw new ProvisionError('identity_changed', 'the server answered for a different person; use --re-enroll if this is intended')
    }
    const identity = { company_id: idn.company_id, person_id: idn.person_id }
    const key = JSON.stringify([identity.company_id, identity.person_id])
    const expected: Expected = { ...identity, aud: AUD, client_version: o.clientVersion }
    if (!hasHistoryFor(state, key)) {
      const bs = reply.bootstrap ?? {}
      if (!isCount(bs.min_generation) || !isCount(bs.min_epoch) || !isCount(bs.min_crl_number)) throw new ProvisionError('reply_invalid')
      expected.min_generation = bs.min_generation
      expected.min_epoch = bs.min_epoch
      expected.min_crl_number = bs.min_crl_number
    }

    // 4. Verify; keep whatever state was reached even when the manifest is refused.
    let payload: ManifestBody
    let client: ClientState
    try {
      const [p, c] = verifyManifest(reply.manifest, { rootPub: o.rootPub, expected, now: now(), state: state.client })
      payload = p as unknown as ManifestBody
      client = c
    } catch (e) {
      if (e instanceof ManifestError) {
        if (e.state && JSON.stringify(e.state) !== JSON.stringify(state.client)) persist({ ...state, client: e.state })
        throw new ProvisionError(`manifest_${e.code}`)
      }
      throw e
    }

    // 5. Accept: persisted BEFORE anything is installed.
    const accepted: WorkspaceState = { ...state, identity, client }
    persist(accepted)

    // 6. Nothing to install when the content is unchanged and intact.
    const hadManagedFile = lexists(join(o.appHome, MANAGED_FILE))
    const managed = readManaged(o.appHome)
    const cd = contentDigest(payload)
    const installedNow: WorkspaceState['installed'] = { generation: payload.generation, epoch: payload.epoch, content_digest: cd }
    const summary = { generation: payload.generation, epoch: payload.epoch, layout: payload.layout.id, mods: payload.mods.map((m) => m.name) }
    if (state.installed?.content_digest === cd && intact(o.appHome).length === 0) {
      persist({ ...accepted, installed: installedNow })
      return { status: 'unchanged' as const, ...summary }
    }

    // 7. Download and verify into staging; the live workspace is untouched until done.
    precheck(payload, o.appHome, managed, o.adopt === true)
    const staging = mkdtempSync(join(o.appHome, '.3pa-staging-'))
    try {
      await stageFiles(o, base, payload, staging)
      assertTime(o) // the last point at which stopping leaves everything as it was
      assertOwned()
      activate(payload, o.appHome, staging, managed, hadManagedFile, fsOps)
    } catch (e) {
      if (!(e instanceof ProvisionError && e.code === 'recovery_required')) rmSync(staging, { recursive: true, force: true })
      throw e
    }
    rmSync(staging, { recursive: true, force: true })
    try {
      persist({ ...accepted, installed: installedNow })
    } catch (e) {
      // The workspace IS updated at this point; only the record of it failed.
      if (e instanceof StateError) throw e
      throw new ProvisionError('state_not_recorded', 'the workspace was updated, but the sync state could not be saved; run the sync again')
    }
    return { status: 'updated' as const, ...summary }
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
  /** An interrupted update is waiting to be rolled back (run `3pa workspace sync`). */
  interrupted: boolean
}

const sha = (buf: Uint8Array) => createHash('sha256').update(buf).digest('hex')

/** Every entry below `dir`, links and special files included and NOT followed. */
function walk(dir: string, base = ''): { rel: string; regular: boolean }[] {
  const out: { rel: string; regular: boolean }[] = []
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const rel = base ? `${base}/${e.name}` : e.name
    if (e.isDirectory()) out.push(...walk(join(dir, e.name), rel))
    else out.push({ rel, regular: e.isFile() })
  }
  return out
}

/** Hash a file only if it is a plain file (a link, even to identical bytes, is a difference). */
function plainHash(path: string): string | null {
  return lstatSync(path).isFile() ? sha(readFileSync(path)) : null
}

/** Compare the app home with what was installed. A diagnostic, not proof: the same user
 * can edit the record too (ADR-0026 decision 4). */
export function scanDrift(appHome: string): Drift {
  const managed = readManaged(appHome)
  const d: Drift = { missing: [], modified: [], unmanagedMods: [], extraFiles: [], interrupted: lexists(join(appHome, JOURNAL_FILE)) }
  if (managed.layout) {
    const rel = `layouts/${managed.layout.name}.json`
    const f = join(appHome, rel)
    if (!lexists(f)) d.missing.push(rel)
    else if (plainHash(f) !== managed.layout.sha256) d.modified.push(rel)
  }
  for (const name of Object.keys(managed.mods)) {
    const m = managed.mods[name]!
    const root = join(appHome, 'mods', name)
    if (!lexists(root)) {
      d.missing.push(`mods/${name}`)
      continue
    }
    const st = lstatSync(root)
    if (st.isSymbolicLink() || !st.isDirectory()) {
      d.modified.push(`mods/${name}`)
      continue
    }
    const present = new Map(walk(root).map((e) => [e.rel, e.regular]))
    for (const path of Object.keys(m.files)) {
      if (!present.has(path)) d.missing.push(`mods/${name}/${path}`)
      else if (!present.get(path) || plainHash(join(root, path)) !== m.files[path]) d.modified.push(`mods/${name}/${path}`)
      present.delete(path)
    }
    for (const extra of present.keys()) d.extraFiles.push(`mods/${name}/${extra}`)
  }
  const modsDir = join(appHome, 'mods')
  if (lexists(modsDir) && lstatSync(modsDir).isDirectory()) {
    for (const e of readdirSync(modsDir, { withFileTypes: true })) {
      if (e.name.startsWith('.') || SHIPPED_MODS.has(e.name) || own(managed.mods, e.name)) continue
      d.unmanagedMods.push(e.name)
    }
  }
  return d
}

function intact(appHome: string): string[] {
  const d = scanDrift(appHome)
  return [...d.missing, ...d.modified, ...d.extraFiles]
}
