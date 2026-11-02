/**
 * Signed release manifest and `3pa self-update` (ADR-0031).
 *
 * What an update may install is decided by a document signed offline with a release key that
 * the installer pinned. The client checks signature, freshness and monotonic order BEFORE it
 * downloads anything, checks every download against the signed size and SHA-256, and publishes
 * only when all downloads are complete. The transport (https) is not what is trusted.
 */

import { createHash, randomBytes } from 'node:crypto'
import { lstatSync, readFileSync, renameSync, rmSync } from 'node:fs'
import { join } from 'node:path'

import { FsError, createFileExclusive, fsyncDir, writeFileAtomic } from './fsutil.js'
import { ManifestError, canonicalBytes, keyId, parseWire, verifyDetached } from './workspace-manifest.js'
import { StateError, ensurePrivateDir, withLock } from './workspace-state.js'

export const RELEASE_DOMAIN = '3pa-release-v1\n'
export const MAX_RELEASE_WIRE = 64 * 1024
export const MAX_RELEASE_LIFETIME = 90 * 24 * 3600
export const MAX_ARTIFACT_BYTES = 200 * 1024 * 1024
export const RELEASE_CLOCK_SKEW = 300
const REQUEST_MAX_MS = 60_000
export const UPDATE_MAX_MS = 20 * 60 * 1000

export class ReleaseError extends Error {
  code: string
  constructor(code: string, message?: string) {
    super(message ?? code)
    this.code = code
  }
}

export type Os = 'linux' | 'macos'
export type Arch = 'x64' | 'arm64'
export interface Artifact { name: '3pa' | 'herdr'; os: Os; arch: Arch; url: string; size: number; sha256: string }
export interface ReleaseBody {
  typ: '3pa-release'; v: 1; channel: string; version: string; seq: number
  issued_at: number; expires_at: number; artifacts: Artifact[]
}
/** The state file holds at most this many channels, so what the updater writes is always
 * far below the size the loader accepts (the two limits are one policy). */
export const MAX_CHANNELS = 16
export const MAX_STATE_BYTES = 64 * 1024
export interface ReleaseState { v: 1; channels: Record<string, { seq: number; version: string; digest: string }> }

const KEYS = ['typ', 'v', 'channel', 'version', 'seq', 'issued_at', 'expires_at', 'artifacts']
const ART_KEYS = ['name', 'os', 'arch', 'url', 'size', 'sha256']
// at most 15 digits per part: every part is then an exact safe integer
const SEMVER = /^(0|[1-9]\d{0,14})\.(0|[1-9]\d{0,14})\.(0|[1-9]\d{0,14})$/
const HEX64 = /^[0-9a-f]{64}$/
const MAX_SAFE = Number.MAX_SAFE_INTEGER

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null && !Array.isArray(x)
const sameKeys = (o: Record<string, unknown>, keys: string[]) =>
  Object.keys(o).length === keys.length && keys.every((k) => Object.hasOwn(o, k))
const int = (x: unknown, min: number, max = MAX_SAFE): x is number => typeof x === 'number' && Number.isSafeInteger(x) && x >= min && x <= max

export function cmpVersion(a: string, b: string): number {
  const pa = a.split('.').map(BigInt), pb = b.split('.').map(BigInt)
  for (let i = 0; i < 3; i++) if (pa[i] !== pb[i]) return pa[i]! < pb[i]! ? -1 : 1
  return 0
}

/** https anywhere; http only for the loopback host names. No credentials or fragment. */
export function checkReleaseUrl(raw: unknown, what = 'url'): string {
  if (typeof raw !== 'string') throw new ReleaseError('bad_url', `the ${what} must be text`)
  let u: URL
  try {
    u = new URL(raw)
  } catch {
    throw new ReleaseError('bad_url', `the ${what} is not a valid URL`)
  }
  const loop = u.hostname === 'localhost' || u.hostname === '127.0.0.1' || u.hostname === '[::1]'
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && loop)) throw new ReleaseError('url_insecure', `the ${what} must be https://`)
  if (u.username || u.password || u.hash || !u.hostname) throw new ReleaseError('bad_url', `the ${what} must not contain credentials or a fragment`)
  return u.href
}

function validateBody(b: unknown, now: number): ReleaseBody {
  const bad = (m: string) => new ReleaseError('release_invalid', m)
  if (!isObj(b) || !sameKeys(b, KEYS)) throw bad('unexpected fields')
  if (b.typ !== '3pa-release' || b.v !== 1) throw bad('wrong type or version')
  if (typeof b.channel !== 'string' || !/^[a-z][a-z0-9-]{0,31}$/.test(b.channel)) throw bad('bad channel')
  if (typeof b.version !== 'string' || !SEMVER.test(b.version)) throw bad('bad version')
  if (!int(b.seq, 1) || !int(b.issued_at, 0) || !int(b.expires_at, 0)) throw bad('bad numbers')
  if (b.expires_at <= b.issued_at || b.expires_at - b.issued_at > MAX_RELEASE_LIFETIME) throw bad('bad lifetime')
  if (b.issued_at > now + RELEASE_CLOCK_SKEW) throw new ReleaseError('release_not_yet_valid')
  if (now >= b.expires_at) throw new ReleaseError('release_expired')
  if (!Array.isArray(b.artifacts) || b.artifacts.length < 1 || b.artifacts.length > 16) throw bad('bad artifact list')
  const seen = new Set<string>()
  for (const a of b.artifacts) {
    if (!isObj(a) || !sameKeys(a, ART_KEYS)) throw bad('unexpected artifact fields')
    if (a.name !== '3pa' && a.name !== 'herdr') throw bad('unknown artifact name')
    if (a.os !== 'linux' && a.os !== 'macos') throw bad('unknown os')
    if (a.arch !== 'x64' && a.arch !== 'arm64') throw bad('unknown arch')
    if (!int(a.size, 1, MAX_ARTIFACT_BYTES)) throw bad('bad size')
    if (typeof a.sha256 !== 'string' || !HEX64.test(a.sha256)) throw bad('bad hash')
    try { checkReleaseUrl(a.url, 'artifact URL') } catch { throw bad('bad artifact URL') }
    const k = `${a.name}/${a.os}/${a.arch}`
    if (seen.has(k)) throw bad('duplicate artifact')
    seen.add(k)
  }
  return b as unknown as ReleaseBody
}

export function emptyReleaseState(): ReleaseState {
  return { v: 1, channels: {} }
}

export function cleanReleaseState(x: unknown): ReleaseState | null {
  if (!isObj(x) || !sameKeys(x, ['v', 'channels']) || x.v !== 1 || !isObj(x.channels)) return null
  const out: ReleaseState = { v: 1, channels: {} }
  if (Object.keys(x.channels).length > MAX_CHANNELS) return null
  for (const [ch, rec] of Object.entries(x.channels)) {
    if (!/^[a-z][a-z0-9-]{0,31}$/.test(ch) || !isObj(rec) || !sameKeys(rec, ['seq', 'version', 'digest'])) return null
    if (!int(rec.seq, 1) || typeof rec.version !== 'string' || !SEMVER.test(rec.version) || typeof rec.digest !== 'string' || !HEX64.test(rec.digest)) return null
    out.channels[ch] = { seq: rec.seq, version: rec.version, digest: rec.digest }
  }
  return out
}

export function loadReleaseState(dir: string): ReleaseState {
  const file = join(dir, 'release-state.json')
  // Only a file that is really absent means "no history". A link (even a dangling one), a
  // folder or anything else is not an absent file: the rollback history must not reset to empty.
  let st
  try {
    st = lstatSync(file)
  } catch (e) {
    const c = (e as NodeJS.ErrnoException).code
    if (c === 'ENOENT' || c === 'ENOTDIR') return emptyReleaseState()
    throw new StateError('state_unreadable', 'the release state could not be inspected')
  }
  if (!st.isFile()) throw new StateError('state_corrupt', 'the release state is not a regular file')
  let parsed: unknown
  try {
    parsed = parseWire(readFileSync(file), MAX_STATE_BYTES) // size cap, duplicate keys, odd numbers refused
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code && !(e instanceof ManifestError)) throw new StateError('state_unreadable', 'the release state could not be read')
    throw new StateError('state_corrupt', 'the release state is damaged')
  }
  const s = cleanReleaseState(parsed)
  if (!s) throw new StateError('state_corrupt', 'the release state is damaged')
  return s
}

export function saveReleaseState(dir: string, s: ReleaseState): void {
  // The exact bytes are checked against the reader's limits BEFORE the old file is replaced, so
  // what is written can always be read back, and a refusal leaves the old state in place.
  if (Object.keys(s.channels).length > MAX_CHANNELS) throw new ReleaseError('release_state_full', `at most ${MAX_CHANNELS} release channels can be tracked on one machine`)
  const text = JSON.stringify(s)
  if (Buffer.byteLength(text) > MAX_STATE_BYTES || !cleanReleaseState(JSON.parse(text))) throw new ReleaseError('release_state_full', 'the release state would be too large to read back')
  ensurePrivateDir(dir)
  writeFileAtomic(join(dir, 'release-state.json'), text)
}

export interface VerifiedRelease { body: ReleaseBody; digest: string }

/** Signature, shape, freshness and order - in that order of authority: nothing in the body is
 * read as meaningful before the signature over it has been verified. */
export function verifyRelease(wire: string | Uint8Array, o: { pub: string; now: number; state: ReleaseState }): VerifiedRelease {
  let env: unknown
  try { env = parseWire(wire, MAX_RELEASE_WIRE) } catch (e) { throw new ReleaseError('release_invalid', `unreadable release document (${(e as ManifestError).code ?? 'error'})`) }
  if (!isObj(env) || !sameKeys(env, ['body', 'kid', 'sig'])) throw new ReleaseError('release_invalid', 'unexpected fields')
  let kid: string
  const rawKey = Buffer.from(String(o.pub), 'base64')
  if (rawKey.length !== 32 || rawKey.toString('base64') !== o.pub) throw new ReleaseError('bad_release_key', 'the pinned release key is not valid')
  try { kid = keyId(o.pub) } catch { throw new ReleaseError('bad_release_key', 'the pinned release key is not valid') }
  if (env.kid !== kid) throw new ReleaseError('release_wrong_key')
  if (!verifyDetached(o.pub, RELEASE_DOMAIN, env.body, env.sig)) throw new ReleaseError('release_bad_signature')
  const body = validateBody(env.body, o.now)
  const digest = createHash('sha256').update(canonicalBytes(body)).digest('hex')
  const prev = o.state.channels[body.channel]
  if (prev) {
    if (body.seq < prev.seq || cmpVersion(body.version, prev.version) < 0) throw new ReleaseError('release_rollback')
    if (body.seq === prev.seq && digest !== prev.digest) throw new ReleaseError('release_conflict')
  }
  return { body, digest }
}

// ── self-update ──────────────────────────────────────────────────────────────

export const DEST: Record<Artifact['name'], string> = { '3pa': '3pa.mjs', herdr: 'herdr' }
export const releaseHooks: { afterStage?: () => void } = {}

export interface UpdateOptions {
  releaseUrl: string
  releasePub: string
  channel?: string
  libDir: string
  stateDir: string
  os: Os
  arch: Arch
  check?: boolean
  fetchImpl?: typeof fetch
  now?: () => number
  maxDurationMs?: number
}
export interface UpdateResult {
  status: 'up_to_date' | 'updated' | 'available'
  version: string
  seq: number
  changed: string[]
}

async function readLimited(res: Response, max: number): Promise<Buffer> {
  const declared = Number(res.headers.get('content-length'))
  if (Number.isFinite(declared) && declared > max) throw new ReleaseError('response_too_large')
  if (!res.body) return Buffer.alloc(0)
  const chunks: Uint8Array[] = []
  let total = 0
  const reader = res.body.getReader()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    total += value.length
    if (total > max) {
      await reader.cancel().catch(() => undefined)
      throw new ReleaseError('response_too_large')
    }
    chunks.push(value)
  }
  return Buffer.concat(chunks)
}

function fileSha(path: string): string | null {
  try {
    if (!lstatSync(path).isFile()) throw new ReleaseError('dest_not_file', `${path} exists and is not a plain file`)
    return createHash('sha256').update(readFileSync(path)).digest('hex')
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw e
  }
}

export async function selfUpdate(o: UpdateOptions): Promise<UpdateResult> {
  const budget = o.maxDurationMs ?? UPDATE_MAX_MS
  if (!Number.isSafeInteger(budget) || budget < 1 || budget > UPDATE_MAX_MS) throw new ReleaseError('bad_duration')
  const f = o.fetchImpl ?? fetch
  const nowSec = () => Math.floor((o.now ? o.now() : Date.now()) / 1000)
  const deadline = Date.now() + budget
  const left = () => {
    const l = deadline - Date.now()
    if (l <= 0) throw new ReleaseError('update_timeout', 'the update took too long and was stopped; nothing was replaced')
    return l
  }
  const get = async (url: string, max: number): Promise<Buffer> => {
    try {
      const res = await f(url, { redirect: 'error', signal: AbortSignal.timeout(Math.min(REQUEST_MAX_MS, left())) })
      if (!res.ok) throw new ReleaseError(`http_${res.status}`)
      return await readLimited(res, max)
    } catch (e) {
      if (e instanceof ReleaseError) throw e
      if ((e as Error)?.name === 'TimeoutError' || (e as Error)?.name === 'AbortError') throw new ReleaseError('update_timeout', 'the server did not answer in time; nothing was replaced')
      throw new ReleaseError('fetch_failed', 'the download failed; nothing was replaced')
    }
  }

  const releaseUrl = checkReleaseUrl(o.releaseUrl, 'release URL')
  return withLock(o.stateDir, async (assertOwned) => {
    const state = loadReleaseState(o.stateDir)
    const wire = await get(releaseUrl, MAX_RELEASE_WIRE)
    const { body, digest } = verifyRelease(wire, { pub: o.releasePub, now: nowSec(), state })
    if (o.channel && body.channel !== o.channel) throw new ReleaseError('release_wrong_channel')
    const mine = body.artifacts.filter((a) => a.os === o.os && a.arch === o.arch)
    if (mine.length === 0) throw new ReleaseError('no_artifact_for_platform')

    const todo: Artifact[] = []
    for (const a of mine) if (fileSha(join(o.libDir, DEST[a.name])) !== a.sha256) todo.push(a)
    const result = (status: UpdateResult['status']): UpdateResult => ({ status, version: body.version, seq: body.seq, changed: todo.map((a) => a.name) })
    if (o.check) return result(todo.length ? 'available' : 'up_to_date')

    // The accepted document is recorded first, so a rollback to an older one is impossible
    // from here on even if a later step fails.
    assertOwned()
    const prev = state.channels[body.channel]
    if (!prev || prev.seq !== body.seq) {
      state.channels[body.channel] = { seq: body.seq, version: body.version, digest }
      saveReleaseState(o.stateDir, state)
    }
    if (todo.length === 0) return result('up_to_date')

    // Download and check everything first; publish only when all of it is good.
    const staged: { tmp: string; dest: string }[] = []
    try {
      for (const a of todo) {
        const data = await get(a.url, a.size)
        if (data.length !== a.size || createHash('sha256').update(data).digest('hex') !== a.sha256) {
          throw new ReleaseError('artifact_mismatch', `the downloaded ${a.name} does not match the signed size/hash; nothing was replaced`)
        }
        const dest = join(o.libDir, DEST[a.name])
        const tmp = join(o.libDir, `.${DEST[a.name]}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`)
        try {
          createFileExclusive(tmp, data, 0o755)
        } catch (e) {
          rmSync(tmp, { force: true })
          if (e instanceof FsError) throw new ReleaseError('fs_error', 'a file could not be written completely; nothing was replaced')
          throw e
        }
        staged.push({ tmp, dest })
        releaseHooks.afterStage?.()
        left()
      }
      assertOwned()
      left()
      // the helper first, then 3pa itself
      staged.sort((x, y) => (x.dest.endsWith('3pa.mjs') ? 1 : 0) - (y.dest.endsWith('3pa.mjs') ? 1 : 0))
      for (const s of staged) {
        renameSync(s.tmp, s.dest)
        s.tmp = ''
      }
      fsyncDir(o.libDir)
    } finally {
      for (const s of staged) if (s.tmp) rmSync(s.tmp, { force: true })
    }
    return result('updated')
  })
}
