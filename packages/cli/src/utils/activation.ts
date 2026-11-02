import { execFile } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { closeSync, fstatSync, lstatSync, openSync, readSync, readdirSync, renameSync, rmSync, utimesSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'

import { writeFileAtomic } from './fsutil.js'
import { ensurePrivateDir } from './workspace-state.js'

/**
 * Storage: every request is its OWN immutable file, `activation.<state>.<key>`, with
 * `<key>` = 13 digits of milliseconds + '-' + 16 hex (so names sort in the order requests were made).
 * There is no shared mutable record, so no two writers can interleave into a half state:
 *   req    a request nobody has taken
 *   claim  taken by a worker (atomic rename req -> claim)
 *   done   honoured or superseded; kept as a marker so that "newer" can still be seen later
 * The NEWEST key among all files, whatever its state, is the request that counts.
 */
const NAME = /^[a-z0-9][a-z0-9._-]{0,63}$/
const ID = /^[0-9a-f]{16}$/
const FILE_RE = /^activation\.(req|claim|done)\.(\d{13})-([0-9a-f]{16})$/
const MAX_BYTES = 4096
const KEEP_MARKERS = 8
export const PENDING_MAX_AGE_MS = 7 * 24 * 3600 * 1000
/** A claim older than this was left by a worker that died (a run is bounded far below it). */
export const STALE_CLAIM_MS = 5 * 60 * 1000
/** Clock skew tolerated in a record's timestamp (the only "future" allowed). */
export const FUTURE_SKEW_MS = 5 * 60 * 1000
export const MAX_WAIT_SECONDS = 120
/** After a window is found: the switch (35 s) and the check that it took (10 s). */
const SWITCH_BUDGET_MS = 45_000

export interface Pending { v: 1; id: string; layout: string; requested_at: number }

export class ActivationError extends Error {
  code: string
  constructor(code: string, message?: string) {
    super(message ?? code)
    this.code = code
  }
}

type State = 'req' | 'claim' | 'done'
interface Entry { state: State; key: string; ts: number; id: string; path: string }
const keyOf = (ts: number, id: string) => `${String(ts).padStart(13, '0')}-${id}`
const pathOf = (dir: string, state: State, key: string) => join(dir, `activation.${state}.${key}`)

/** Every request file of the folder, oldest first. Anything else in the folder is ignored. */
function entries(stateDir: string): Entry[] {
  const out: Entry[] = []
  for (const name of readdirSync(stateDir)) {
    const m = FILE_RE.exec(name)
    if (m) out.push({ state: m[1] as State, key: `${m[2]}-${m[3]}`, ts: Number(m[2]), id: m[3]!, path: join(stateDir, name) })
  }
  return out.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
}

/** Keep the newest few files (the markers); the rest are history. */
function prune(stateDir: string): void {
  const all = entries(stateDir)
  for (const e of all.slice(0, Math.max(0, all.length - KEEP_MARKERS))) rmSync(e.path, { force: true })
}

export function requestActivation(stateDir: string, layout: string, now = Date.now()): void {
  if (!NAME.test(layout)) throw new ActivationError('bad_layout')
  ensurePrivateDir(stateDir)
  // never older than a request already on file (a clock that stepped back must not make a new
  // request look superseded)
  const newest = entries(stateDir).at(-1)
  const ts = Math.max(now, newest ? newest.ts + 1 : 0)
  const id = randomBytes(8).toString('hex')
  const rec: Pending = { v: 1, id, layout, requested_at: ts }
  writeFileAtomic(pathOf(stateDir, 'req', keyOf(ts, id)), JSON.stringify(rec))
  prune(stateDir)
}

/** Reads at most MAX_BYTES of a regular file without following a link; null on anything else. */
function readSmall(path: string): string | null {
  let fd: number
  try {
    if (!lstatSync(path).isFile()) return null
    fd = openSync(path, 'r')
  } catch {
    return null
  }
  try {
    const st = fstatSync(fd)
    if (!st.isFile() || st.size > MAX_BYTES) return null
    const buf = Buffer.alloc(st.size)
    readSync(fd, buf, 0, st.size, 0)
    return buf.toString('utf8')
  } catch {
    return null
  } finally {
    closeSync(fd)
  }
}

/** The record in an entry's file, only if its content agrees with its name. */
function parse(e: Entry, now: number): Pending | null {
  const raw = readSmall(e.path)
  if (raw === null) return null
  let j: unknown
  try { j = JSON.parse(raw) } catch { return null }
  if (typeof j !== 'object' || j === null || Array.isArray(j)) return null
  const o = j as Record<string, unknown>
  if (Object.keys(o).length !== 4 || o.v !== 1) return null
  if (typeof o.id !== 'string' || !ID.test(o.id) || o.id !== e.id) return null
  if (typeof o.layout !== 'string' || !NAME.test(o.layout)) return null
  if (typeof o.requested_at !== 'number' || !Number.isSafeInteger(o.requested_at) || o.requested_at !== e.ts) return null
  if (now - o.requested_at > PENDING_MAX_AGE_MS || o.requested_at > now + FUTURE_SKEW_MS) return null
  return { v: 1, id: o.id, layout: o.layout, requested_at: o.requested_at }
}

/** Only a state folder that is the caller's own, private and not a link is trusted at all. */
function trusted(stateDir: string): boolean {
  try {
    ensurePrivateDir(stateDir)
    return true
  } catch {
    return false
  }
}

/** The request waiting to be served: the NEWEST request, if nobody has taken it. Absent, damaged,
 * expired, in an untrusted folder, or superseded by a taken/served newer one all mean "nothing". */
export function loadPending(stateDir: string, now = Date.now()): Pending | null {
  if (!trusted(stateDir)) return null
  const newest = entries(stateDir).at(-1)
  return newest && newest.state === 'req' ? parse(newest, now) : null
}

export interface Claim { path: string; key: string; pending: Pending; stateDir: string }

/** Is `key` still the newest request of the folder (nothing newer, in any state)? */
function isNewest(stateDir: string, key: string): boolean {
  const newest = entries(stateDir).at(-1)
  return !newest || newest.key <= key
}

/** Give back claims left by workers that died - if they are still the newest request. */
function recoverStale(stateDir: string, now: number): void {
  for (const e of entries(stateDir)) {
    if (e.state !== 'claim') continue
    try {
      if (now - lstatSync(e.path).mtimeMs < STALE_CLAIM_MS) continue
      if (isNewest(stateDir, e.key) && parse(e, now)) renameSync(e.path, pathOf(stateDir, 'req', e.key))
      else rmSync(e.path, { force: true })
    } catch { /* gone already */ }
  }
}

/** Take the newest request for this worker: one atomic rename. Of several workers exactly one gets
 * it; older requests are superseded and removed. */
export function claim(stateDir: string, now = Date.now()): Claim | null {
  if (!trusted(stateDir)) return null
  recoverStale(stateDir, now)
  return claimNow(stateDir, now)
}

function claimNow(stateDir: string, now: number): Claim | null {
  const all = entries(stateDir)
  const newest = all.at(-1)
  if (!newest || newest.state !== 'req') return null
  for (const old of all) if (old.state === 'req' && old.key < newest.key) rmSync(old.path, { force: true }) // superseded
  const path = pathOf(stateDir, 'claim', newest.key)
  try {
    renameSync(newest.path, path)
  } catch {
    return null // another worker took it
  }
  try { utimesSync(path, now / 1000, now / 1000) } catch { /* only affects staleness */ }
  const e: Entry = { ...newest, state: 'claim', path }
  const pending = parse(e, now)
  if (!pending) {
    rmSync(path, { force: true })
    return null
  }
  return { path, key: newest.key, pending, stateDir }
}

/** Done (served, or no longer wanted): the claim stays as a marker, so that a request made
 * after it is recognisably newer. Not done: it goes back - unless something newer exists. */
export function release(c: Claim, done: boolean): void {
  try {
    if (!done && isNewest(c.stateDir, c.key)) renameSync(c.path, pathOf(c.stateDir, 'req', c.key))
    else if (done) renameSync(c.path, pathOf(c.stateDir, 'done', c.key))
    else rmSync(c.path, { force: true })
  } catch {
    rmSync(c.path, { force: true })
  }
  try { prune(c.stateDir) } catch { /* history only */ }
}

export interface Ran { code: number | null; stdout: string }
export type Runner = (bin: string, args: string[], env: NodeJS.ProcessEnv, timeoutMs: number) => Promise<Ran>

export const realRunner: Runner = (bin, args, env, timeoutMs) =>
  new Promise((resolve) => {
    execFile(bin, args, { env, timeout: timeoutMs, windowsHide: true, maxBuffer: 1024 * 1024 }, (err, stdout) => {
      const code = err ? ((err as NodeJS.ErrnoException & { code?: number | string }).code as unknown) : 0
      resolve({ code: typeof code === 'number' ? code : err ? 1 : 0, stdout: String(stdout ?? '') })
    })
  })

export interface ActivateOptions {
  stateDir: string
  appHome: string
  herdrBin: string
  /** Wait this long (a real deadline, status calls included) for a window to appear (0: look once). */
  waitSeconds?: number
  runner?: Runner
  sleep?: (ms: number) => Promise<void>
  /** Wall clock in ms (record ages). */
  now?: () => number
  /** Monotonic clock in ms (waiting budget); defaults to performance.now(). */
  clock?: () => number
}

export type Outcome = 'nothing' | 'switched' | 'already' | 'no_window' | 'failed' | 'superseded'

/** The layout the open window shows; undefined when there is no window; null when it cannot be read. */
async function shownLayout(o: ActivateOptions, run: Runner, env: NodeJS.ProcessEnv, timeoutMs: number): Promise<string | null | undefined> {
  const r = await run(o.herdrBin, ['status'], env, timeoutMs)
  if (r.code !== 0) return undefined // no window (the app says so with a non-zero exit)
  try {
    const j = JSON.parse(r.stdout) as { layout?: unknown }
    return typeof j.layout === 'string' && NAME.test(j.layout) ? j.layout : null
  } catch {
    return null
  }
}

export async function activate(o: ActivateOptions): Promise<Outcome> {
  const wall = o.now ?? Date.now
  const clock = o.clock ?? (() => performance.now())
  // A dead worker's claim comes back first, so the check below can see it (ACT-4).
  if (!trusted(o.stateDir)) return 'nothing'
  recoverStale(o.stateDir, wall())
  // Look at the request without taking it, so a bad binary path does not consume it.
  if (!loadPending(o.stateDir, wall())) return 'nothing'
  if (!isAbsolute(o.herdrBin)) throw new ActivationError('herdr_bin_not_absolute')
  try {
    if (!lstatSync(o.herdrBin).isFile()) throw new ActivationError('herdr_bin_not_a_file')
  } catch (e) {
    if (e instanceof ActivationError) throw e
    throw new ActivationError('herdr_bin_missing')
  }
  const mine = claimNow(o.stateDir, wall())
  if (!mine) return 'nothing' // another worker has it (or it just went)
  let done = false
  try {
    const { layout } = mine.pending
    const wait = Math.max(0, Math.min(MAX_WAIT_SECONDS, Math.floor(o.waitSeconds ?? 0)))
    const run = o.runner ?? realRunner
    const sleep = o.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)))
    const env = { ...process.env, HERDR_APP_HOME: o.appHome }
    const deadline = clock() + wait * 1000
    const stillWanted = () => stillValid(mine.pending, wall())

    let shown: string | null | undefined
    for (let first = true; ; first = false) {
      const remaining = deadline - clock()
      if (!first && remaining <= 0) break // the deadline is the deadline: no new look after it
      // one look with no wait may take its 10 s; with a wait, no look outlasts what is left
      shown = await shownLayout(o, run, env, wait === 0 ? 10_000 : Math.max(1, Math.min(10_000, remaining)))
      if (shown !== undefined) break
      const left = deadline - clock()
      if (left <= 0 || !stillWanted()) break
      await sleep(Math.min(1000, left))
    }
    if (shown === undefined) return 'no_window' // not started yet: the request goes back for the next time
    if (!stillWanted()) { done = true; return 'nothing' } // expired while waiting
    if (shown === layout) { done = true; return 'already' }
    // a newer request exists (waiting, or already taken by another worker): it decides
    if (!isNewest(o.stateDir, mine.key)) { done = true; return 'superseded' }
    const sw = await run(o.herdrBin, ['do', 'layout.switch', '--name', layout], env, SWITCH_BUDGET_MS - 10_000)
    if (sw.code !== 0) return 'failed'
    const after = await shownLayout(o, run, env, 10_000)
    if (after !== layout) return 'failed' // the app said yes but is not showing it: keep the request
    done = true
    return 'switched'
  } finally {
    release(mine, done)
  }
}

function stillValid(p: Pending, now: number): boolean {
  return now - p.requested_at <= PENDING_MAX_AGE_MS
}
