import { execFile } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { closeSync, existsSync, fstatSync, linkSync, lstatSync, openSync, readSync, readdirSync, renameSync, rmSync, utimesSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'

import { writeFileAtomic } from './fsutil.js'
import { ensurePrivateDir } from './workspace-state.js'

const FILE = 'activation.json'
/** The id of the NEWEST request ever made, kept after the request itself has been taken: a worker
 * that still holds an older one can tell it is no longer wanted. */
const HEAD = 'activation.head'
const CLAIM = /^activation\.claimed\.[0-9a-f]{16}$/
const NAME = /^[a-z0-9][a-z0-9._-]{0,63}$/
const ID = /^[0-9a-f]{16}$/
const MAX_BYTES = 4096
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

export function requestActivation(stateDir: string, layout: string, now = Date.now()): void {
  if (!NAME.test(layout)) throw new ActivationError('bad_layout')
  ensurePrivateDir(stateDir)
  const rec: Pending = { v: 1, id: randomBytes(8).toString('hex'), layout, requested_at: now }
  const text = JSON.stringify(rec)
  // Head first: a worker that claims the new request already sees it as the newest, and a worker
  // holding an older one sees it superseded before the new request file even exists.
  writeFileAtomic(join(stateDir, HEAD), text)
  writeFileAtomic(join(stateDir, FILE), text)
}

/** The newest request's id, or null when unknown (no head, damaged, untrusted folder). */
function headId(stateDir: string, now: number): string | null {
  return parse(readSmall(join(stateDir, HEAD)), now)?.id ?? null
}

/** Is this still the newest request? An unknown head counts as "yes" only for a request that
 * predates the head file (none exist yet), so unknown means no: the caller does nothing. */
function isNewest(stateDir: string, id: string, now: number): boolean {
  return headId(stateDir, now) === id
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

function parse(raw: string | null, now: number): Pending | null {
  if (raw === null) return null
  let j: unknown
  try { j = JSON.parse(raw) } catch { return null }
  if (typeof j !== 'object' || j === null || Array.isArray(j)) return null
  const o = j as Record<string, unknown>
  if (Object.keys(o).length !== 4 || o.v !== 1) return null
  if (typeof o.id !== 'string' || !ID.test(o.id) || typeof o.layout !== 'string' || !NAME.test(o.layout)) return null
  if (typeof o.requested_at !== 'number' || !Number.isSafeInteger(o.requested_at) || o.requested_at < 0) return null
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

/** The pending request, or null: absent, damaged, unknown shape, older than a week, or in a folder
 * that is not this user's private one all mean "nothing to do" (a record must never turn into a
 * switch to an arbitrary name). */
export function loadPending(stateDir: string, now = Date.now()): Pending | null {
  if (!trusted(stateDir)) return null
  return parse(readSmall(join(stateDir, FILE)), now)
}

export interface Claim { path: string; pending: Pending; stateDir: string }

/** Put back claims left by workers that died (rename = atomic; a newer request wins). */
function recoverStale(stateDir: string, now: number): void {
  for (const name of readdirSync(stateDir)) {
    if (!CLAIM.test(name)) continue
    const path = join(stateDir, name)
    try {
      const st = lstatSync(path)
      if (!st.isFile() || now - st.mtimeMs < STALE_CLAIM_MS) continue
      const old = parse(readSmall(path), now)
      // restored only if it is still the newest request and no newer file is waiting
      if (old && isNewest(stateDir, old.id, now)) {
        try { linkSync(path, join(stateDir, FILE)) } catch { /* a newer request is there: it wins */ }
      }
      rmSync(path, { force: true })
    } catch { /* gone already */ }
  }
}

/** Take the request for this worker: one atomic rename, so of several workers exactly one gets it
 * and a request written afterwards is a different file that nobody here can remove. */
export function claim(stateDir: string, now = Date.now()): Claim | null {
  if (!trusted(stateDir)) return null
  recoverStale(stateDir, now)
  return claimNow(stateDir, now)
}

function claimNow(stateDir: string, now: number): Claim | null {
  const path = join(stateDir, `activation.claimed.${randomBytes(8).toString('hex')}`)
  try {
    renameSync(join(stateDir, FILE), path)
  } catch {
    return null // nothing pending, or another worker took it
  }
  try { utimesSync(path, now / 1000, now / 1000) } catch { /* only affects staleness */ }
  const pending = parse(readSmall(path), now)
  if (!pending) {
    rmSync(path, { force: true })
    return null
  }
  return { path, pending, stateDir }
}

/** Done: the claim is removed. Not done: it goes back unless a newer request already exists. */
export function release(c: Claim, done: boolean, now = Date.now()): void {
  if (!done && isNewest(c.stateDir, c.pending.id, now)) {
    try { linkSync(c.path, join(c.stateDir, FILE)) } catch { /* a newer request wins, or the folder is gone */ }
  }
  rmSync(c.path, { force: true })
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
    if (existsSync(join(o.stateDir, FILE)) || !isNewest(o.stateDir, mine.pending.id, wall())) { done = true; return 'superseded' }
    const sw = await run(o.herdrBin, ['do', 'layout.switch', '--name', layout], env, SWITCH_BUDGET_MS - 10_000)
    if (sw.code !== 0) return 'failed'
    const after = await shownLayout(o, run, env, 10_000)
    if (after !== layout) return 'failed' // the app said yes but is not showing it: keep the request
    done = true
    return 'switched'
  } finally {
    release(mine, done, wall())
  }
}

function stillValid(p: Pending, now: number): boolean {
  return now - p.requested_at <= PENDING_MAX_AGE_MS
}
