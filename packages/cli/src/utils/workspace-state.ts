/**
 * Durable client state for the workspace provisioner (ADR-0027, ADR-0029).
 *
 * The state holds what rollback protection depends on (accepted generation per person,
 * signing epoch, revocation list, last clock reading) and which person this machine is
 * enrolled as. It is written atomically (temp file in the same directory, fsync, rename),
 * mode 0600 in a 0700 directory, and a second provisioner run is kept out by a lock.
 *
 * A corrupt or unreadable state file is NEVER reset silently: starting from zero is the
 * very replay the state exists to prevent, so the caller must be told and an operator
 * must decide (`--re-enroll`, which asks the server for fresh floors).
 */

import {
  closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync,
  renameSync, rmSync, writeSync,
} from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { randomBytes } from 'node:crypto'

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

function isState(x: unknown): x is WorkspaceState {
  if (typeof x !== 'object' || x === null) return false
  const s = x as Partial<WorkspaceState>
  const c = s.client as Partial<ClientState> | undefined
  return (
    s.v === 1 && typeof c === 'object' && c !== null &&
    typeof c.generations === 'object' && c.generations !== null &&
    Number.isInteger(c.epoch) && Number.isInteger(c.crl_number) && Number.isInteger(c.last_seen) &&
    Array.isArray(c.revoked) && typeof c.signing_kid === 'string' &&
    typeof c.crl_digest === 'string' && Number.isInteger(c.crl_next_update)
  )
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
  if (!isState(parsed)) throw new StateError('state_corrupt', 'state.json has an unexpected shape')
  return parsed
}

export function saveState(dir: string, state: WorkspaceState): void {
  ensurePrivateDir(dir)
  const tmp = join(dir, `.state-${randomBytes(6).toString('hex')}.tmp`)
  const fd = openSync(tmp, 'wx', 0o600)
  try {
    writeSync(fd, JSON.stringify(state, null, 2))
    fsyncSync(fd)
  } finally {
    closeSync(fd)
  }
  renameSync(tmp, join(dir, 'state.json'))
  try {
    const dfd = openSync(dir, 'r')
    try {
      fsyncSync(dfd)
    } finally {
      closeSync(dfd)
    }
  } catch {
    /* directory fsync is best effort (not supported everywhere) */
  }
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch (e) {
    return (e as NodeJS.ErrnoException).code === 'EPERM'
  }
}

/** Run `fn` while holding an exclusive lock; a second run fails fast with `locked`.
 * A lock left by a process that no longer exists is taken over. */
export async function withLock<T>(dir: string, fn: () => Promise<T>): Promise<T> {
  ensurePrivateDir(dir)
  const lock = join(dir, 'sync.lock')
  for (let attempt = 0; ; attempt++) {
    try {
      const fd = openSync(lock, 'wx', 0o600)
      writeSync(fd, String(process.pid))
      closeSync(fd)
      break
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== 'EEXIST') throw e
      let holder = NaN
      try {
        holder = Number(readFileSync(lock, 'utf8'))
      } catch {
        /* vanished: retry */
      }
      if (attempt === 0 && (!Number.isInteger(holder) || !alive(holder))) {
        rmSync(lock, { force: true }) // stale
        continue
      }
      throw new StateError('locked', 'another workspace sync is running')
    }
  }
  try {
    return await fn()
  } finally {
    rmSync(lock, { force: true })
  }
}

