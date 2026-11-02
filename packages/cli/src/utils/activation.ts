/**
 * Showing the person their layout (ADR-0036).
 *
 * The provisioner installs `layouts/<id>.json`; Herdr keeps showing whatever layout the person last
 * had (`main` on a fresh home) until told otherwise. The supported way to tell it is the app's own
 * command, `herdr-app do layout.switch --name <id>`, which reaches the OPEN window over its control
 * socket in the app home; `herdr-app status` says which layout is shown. Nothing else is touched:
 * no file of Herdr's is written, no process is signalled.
 *
 * A switch is requested once per CHANGE of layout id (first install, or a different id), kept as a
 * small pending record in the private state folder, and done when a window is there. A person who
 * then moves to another layout on purpose is not fought: the record is cleared once it has been
 * honoured, and an unanswered one expires.
 */

import { execFile } from 'node:child_process'
import { lstatSync, readFileSync, rmSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'

import { writeFileAtomic } from './fsutil.js'
import { ensurePrivateDir } from './workspace-state.js'

const FILE = 'activation.json'
const NAME = /^[a-z0-9][a-z0-9._-]{0,63}$/
export const PENDING_MAX_AGE_MS = 7 * 24 * 3600 * 1000
export const MAX_WAIT_SECONDS = 120

export interface Pending { v: 1; layout: string; requested_at: number }

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
  writeFileAtomic(join(stateDir, FILE), JSON.stringify({ v: 1, layout, requested_at: now } satisfies Pending))
}

/** The pending request, or null: absent, damaged, unknown shape or older than a week all mean
 * "nothing to do" (a damaged record must never turn into a switch to an arbitrary name). */
export function loadPending(stateDir: string, now = Date.now()): Pending | null {
  const file = join(stateDir, FILE)
  let raw: string
  try {
    if (!lstatSync(file).isFile()) return null
    raw = readFileSync(file, 'utf8')
  } catch {
    return null
  }
  if (raw.length > 4096) return null
  let j: unknown
  try { j = JSON.parse(raw) } catch { return null }
  if (typeof j !== 'object' || j === null || Array.isArray(j)) return null
  const o = j as Record<string, unknown>
  const keys = Object.keys(o)
  if (keys.length !== 3 || o.v !== 1 || typeof o.layout !== 'string' || !NAME.test(o.layout)) return null
  if (typeof o.requested_at !== 'number' || !Number.isSafeInteger(o.requested_at) || o.requested_at < 0) return null
  if (now - o.requested_at > PENDING_MAX_AGE_MS || o.requested_at > now + 5 * 60 * 1000) return null
  return { v: 1, layout: o.layout, requested_at: o.requested_at }
}

/** Removes the record only if it still asks for `layout` (a newer request must survive). */
export function clearPending(stateDir: string, layout: string, now = Date.now()): void {
  const p = loadPending(stateDir, now)
  if (!p || p.layout !== layout) return
  rmSync(join(stateDir, FILE), { force: true })
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
  /** Wait this long for a window to appear (0: look once). */
  waitSeconds?: number
  runner?: Runner
  sleep?: (ms: number) => Promise<void>
  now?: () => number
}

export type Outcome = 'nothing' | 'switched' | 'already' | 'no_window' | 'failed'

/** The layout the open window shows, or null when there is no window / no readable answer. */
async function shownLayout(o: ActivateOptions, run: Runner, env: NodeJS.ProcessEnv): Promise<string | null | undefined> {
  const r = await run(o.herdrBin, ['status'], env, 10_000)
  if (r.code !== 0) return undefined // no window (the app says so with a non-zero exit)
  try {
    const j = JSON.parse(r.stdout) as { layout?: unknown }
    return typeof j.layout === 'string' && NAME.test(j.layout) ? j.layout : null
  } catch {
    return null
  }
}

export async function activate(o: ActivateOptions): Promise<Outcome> {
  const pending = loadPending(o.stateDir, (o.now ?? Date.now)())
  if (!pending) return 'nothing'
  if (!isAbsolute(o.herdrBin)) throw new ActivationError('herdr_bin_not_absolute')
  try {
    if (!lstatSync(o.herdrBin).isFile()) throw new ActivationError('herdr_bin_not_a_file')
  } catch (e) {
    if (e instanceof ActivationError) throw e
    throw new ActivationError('herdr_bin_missing')
  }
  const wait = Math.max(0, Math.min(MAX_WAIT_SECONDS, Math.floor(o.waitSeconds ?? 0)))
  const run = o.runner ?? realRunner
  const sleep = o.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)))
  const env = { ...process.env, HERDR_APP_HOME: o.appHome }

  let shown: string | null | undefined
  for (let i = 0; ; i++) {
    shown = await shownLayout(o, run, env)
    if (shown !== undefined || i >= wait) break
    await sleep(1000)
  }
  if (shown === undefined) return 'no_window' // not started yet: the request stays for the next time
  if (shown === pending.layout) {
    clearPending(o.stateDir, pending.layout, (o.now ?? Date.now)())
    return 'already'
  }
  const sw = await run(o.herdrBin, ['do', 'layout.switch', '--name', pending.layout], env, 35_000)
  if (sw.code !== 0) return 'failed'
  const after = await shownLayout(o, run, env)
  if (after !== pending.layout) return 'failed' // the app said yes but is not showing it: keep the request
  clearPending(o.stateDir, pending.layout, (o.now ?? Date.now)())
  return 'switched'
}
