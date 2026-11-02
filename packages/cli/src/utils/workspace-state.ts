/**
 * Durable client state for the workspace provisioner (ADR-0027, ADR-0029).
 *
 * The state holds what rollback protection depends on (accepted generation per person,
 * signing epoch, revocation list, last clock reading) and which person this machine is
 * enrolled as. It is written atomically, mode 0600 in a 0700 directory, and a second
 * provisioner run is kept out by a lock.
 *
 * A corrupt or unreadable state file is NEVER reset silently: starting from zero is the
 * very replay the state exists to prevent, so the caller must be told and an operator
 * must decide (`--re-enroll`, which asks the server for fresh floors). "Corrupt" includes
 * a file that parses as JSON but whose fields are not what the verifier expects: every
 * field is checked, because JavaScript would otherwise coerce a damaged counter into a
 * comparison that quietly passes.
 */

import {
  closeSync, existsSync, lstatSync, mkdirSync, openSync, readFileSync, renameSync, rmSync,
  linkSync, fsyncSync,
} from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { randomBytes } from 'node:crypto'

import { fsyncDir, writeAll, writeFileAtomic } from './fsutil.js'
import { type ClientState, emptyState } from './workspace-manifest.js'

export interface InstalledRecord {
  generation: number
  epoch: number
  /** sha256 over the canonical {layout, mods}: equal content means nothing to do. */
  content_digest: string
}

export interface WorkspaceState {
  v: 1
  identity?: { company_id: string; person_id: string }
  client: ClientState
  installed?: InstalledRecord
}

export class StateError extends Error {
  code: string
  constructor(code: string, message?: string) {
    super(message ?? code)
    this.code = code
  }
}

export function workspaceStateDir(): string {
  return process.env.THREEPA_WORKSPACE_DIR || join(homedir(), '.config', '3pa', 'workspace')
}

export function freshState(): WorkspaceState {
  return { v: 1, client: emptyState() }
}

/** Create the directory 0700 and refuse a symlink or someone else's directory. */
export function ensurePrivateDir(dir: string): void {
  mkdirSync(dir, { recursive: true, mode: 0o700 })
  const st = lstatSync(dir)
  if (st.isSymbolicLink() || !st.isDirectory()) throw new StateError('state_dir_unsafe')
  if (typeof process.getuid === 'function' && st.uid !== process.getuid()) throw new StateError('state_dir_unsafe')
  if ((st.mode & 0o077) !== 0) throw new StateError('state_dir_unsafe', 'state directory must be 0700')
}

// ── strict shape ─────────────────────────────────────────────────────────────

const HEX64 = /^[0-9a-f]{64}$/
const KID = /^[0-9a-f]{32}$/
const ID = /^[A-Za-z0-9_-]{1,64}$/
const own = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k)
const isObj = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null && !Array.isArray(x)
const safeInt = (x: unknown, min = 0): x is number => Number.isSafeInteger(x) && (x as number) >= min

/** Binding key as the verifier writes it: a JSON array of the two ids. */
function validBindingKey(k: string): boolean {
  try {
    const a = JSON.parse(k)
    return Array.isArray(a) && a.length === 2 && ID.test(a[0]) && ID.test(a[1]) && JSON.stringify(a) === k
  } catch {
    return false
  }
}

/** Returns a clean copy (no inherited or extra fields) or null. */
export function cleanState(x: unknown): WorkspaceState | null {
  if (!isObj(x) || x.v !== 1 || !isObj(x.client)) return null
  const c = x.client
  if (!isObj(c.generations)) return null
  const generations: ClientState['generations'] = {}
  for (const k of Object.keys(c.generations)) {
    const g = c.generations[k]
    if (!validBindingKey(k) || !isObj(g) || !safeInt(g.generation, 1) || typeof g.digest !== 'string' || !HEX64.test(g.digest)) return null
    generations[k] = { generation: g.generation, digest: g.digest }
  }
  if (!safeInt(c.epoch) || !safeInt(c.crl_number) || !safeInt(c.crl_next_update) || !safeInt(c.last_seen)) return null
  if (typeof c.crl_digest !== 'string' || (c.crl_digest !== '' && !HEX64.test(c.crl_digest))) return null
  if (typeof c.signing_kid !== 'string' || (c.signing_kid !== '' && !KID.test(c.signing_kid))) return null
  if (!Array.isArray(c.revoked) || c.revoked.some((k) => typeof k !== 'string' || !KID.test(k)) || new Set(c.revoked).size !== c.revoked.length) return null
  const client: ClientState = {
    generations, epoch: c.epoch, crl_number: c.crl_number, crl_digest: c.crl_digest,
    crl_next_update: c.crl_next_update, revoked: [...(c.revoked as string[])], last_seen: c.last_seen, signing_kid: c.signing_kid,
  }
  const out: WorkspaceState = { v: 1, client }
  if (x.identity !== undefined) {
    const i = x.identity
    if (!isObj(i) || typeof i.company_id !== 'string' || !ID.test(i.company_id) || typeof i.person_id !== 'string' || !ID.test(i.person_id)) return null
    out.identity = { company_id: i.company_id, person_id: i.person_id }
  }
  if (x.installed !== undefined) {
    const n = x.installed
    if (!isObj(n) || !safeInt(n.generation, 1) || !safeInt(n.epoch, 1) || typeof n.content_digest !== 'string' || !HEX64.test(n.content_digest)) return null
    out.installed = { generation: n.generation, epoch: n.epoch, content_digest: n.content_digest }
  }
  return out
}

export function hasHistoryFor(state: WorkspaceState, key: string): boolean {
  return state.client.epoch > 0 && own(state.client.generations, key)
}

/** `null` when there is no state yet (first enrolment); throws when it exists but is bad. */
export function loadState(dir: string): WorkspaceState | null {
  const file = join(dir, 'state.json')
  if (!existsSync(file)) return null
  const st = lstatSync(file)
  if (st.isSymbolicLink() || !st.isFile()) throw new StateError('state_corrupt', 'state.json is not a regular file')
  let parsed: unknown
  try {
    parsed = JSON.parse(readFileSync(file, 'utf8'))
  } catch {
    throw new StateError('state_corrupt', 'state.json is not valid JSON')
  }
  const clean = cleanState(parsed)
  if (!clean) throw new StateError('state_corrupt', 'state.json has an unexpected shape')
  return clean
}

export function saveState(dir: string, state: WorkspaceState): void {
  ensurePrivateDir(dir)
  writeFileAtomic(join(dir, 'state.json'), JSON.stringify(state, null, 2))
}

// ── lock ─────────────────────────────────────────────────────────────────────

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch (e) {
    return (e as NodeJS.ErrnoException).code === 'EPERM'
  }
}

function readLock(path: string): { raw: string; pid: number; token: string } | null {
  let raw: string
  try {
    raw = readFileSync(path, 'utf8')
  } catch {
    return null
  }
  try {
    const j = JSON.parse(raw) as { pid?: unknown; token?: unknown }
    return { raw, pid: typeof j.pid === 'number' ? j.pid : NaN, token: typeof j.token === 'string' ? j.token : '' }
  } catch {
    return { raw, pid: NaN, token: '' }
  }
}

/**
 * Run `fn` while holding an exclusive lock; a second run fails fast with `locked`.
 *
 * The lock file carries this run's pid and a random token. Unlock only removes a file that
 * still carries OUR token, and `assertOwned()` lets the critical section re-check that the
 * lock was not lost. A lock whose process is gone is taken over by moving it aside and
 * checking that what was moved is what was judged stale; if it turns out to be somebody
 * else's live lock it is put back and this run backs off. Node has no portable OS file lock,
 * so a true multi-process race on the takeover itself is narrowed, not eliminated: a process
 * that ends up not holding the lock finds out at `assertOwned()` and stops before it writes.
 */
/** Test seam: runs after a stale holder was read and before it is moved aside. */
export const lockHooks: { afterReadStale?: () => void } = {}

export async function withLock<T>(dir: string, fn: (assertOwned: () => void) => Promise<T>): Promise<T> {
  ensurePrivateDir(dir)
  const lock = join(dir, 'sync.lock')
  const token = randomBytes(12).toString('hex')
  const body = JSON.stringify({ pid: process.pid, token })

  let acquired = false
  for (let attempt = 0; attempt < 3 && !acquired; attempt++) {
    try {
      const fd = openSync(lock, 'wx', 0o600)
      try {
        writeAll(fd, Buffer.from(body))
        fsyncSync(fd)
      } finally {
        closeSync(fd)
      }
      acquired = true
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== 'EEXIST') throw e
      const holder = readLock(lock)
      if (holder === null) continue // vanished between the two calls: try again
      if (Number.isInteger(holder.pid) && alive(holder.pid)) throw new StateError('locked', 'another workspace sync is running')
      lockHooks.afterReadStale?.()
      // looks stale: move it aside, then check we moved the file we judged
      const aside = `${lock}.stale-${randomBytes(6).toString('hex')}`
      try {
        renameSync(lock, aside)
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === 'ENOENT') continue
        throw err
      }
      const moved = readLock(aside)
      if (moved && moved.raw === holder.raw) {
        rmSync(aside, { force: true })
        continue
      }
      // we moved something else - most likely a live lock created in the meantime
      try {
        linkSync(aside, lock)
      } catch {
        /* the owner will notice at assertOwned() */
      }
      rmSync(aside, { force: true })
      throw new StateError('locked', 'another workspace sync is running')
    }
  }
  if (!acquired) throw new StateError('locked', 'could not take the sync lock')
  fsyncDir(dir)

  const owned = () => readLock(lock)?.token === token
  try {
    return await fn(() => {
      if (!owned()) throw new StateError('lock_lost', 'the sync lock was taken over; nothing further was written')
    })
  } finally {
    if (owned()) rmSync(lock, { force: true })
  }
}
