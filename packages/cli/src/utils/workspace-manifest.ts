/**
 * Verifier for the signed workspace manifest (ADR-0027). A TypeScript port of
 * `backend/services/workspace_manifest.py`: it must give the same answer for every
 * case in `backend/tests/vectors/workspace_manifest_vectors.json` (see
 * `test/workspace-manifest.test.ts`). It verifies only; nothing is installed here.
 *
 * Trust chain: pinned root key -> root-signed signing certificate -> signed manifest.
 * Untrusted bytes go through `parseWire` first (duplicate keys, floats, `-0`, unsafe
 * integers and lone surrogates are rejected rather than resolved per parser), and the
 * canonical form is byte-identical to Python's: keys sorted by UTF-16 code unit,
 * everything outside U+0020-U+007E escaped as lower-case \uXXXX.
 *
 * Untrusted JSON must enter through `verifyWire` / `parseWire`: a plain JS object cannot tell
 * `1` from `1.0`, so `canonicalBytes` on an already-parsed object is only for data this
 * program built itself. Documents nested deeper than 500 levels are refused as `too_deep`
 * while still being read (a recursion bound); beyond that depth the first-fault order that
 * Python gives is not reproduced - both refuse.
 *
 * Paths are ASCII-only (`[A-Za-z0-9._@+-]` per component), so there are no normalisation or
 * case-folding tables to keep in step with Python. A collision the provisioner still misses
 * on a case-insensitive filesystem aborts the install, because files are created with O_EXCL.
 */

import { createHash, createPublicKey, verify as edVerify } from 'node:crypto'

export const MAX_MANIFEST_LIFETIME = 24 * 3600
export const MAX_CERT_LIFETIME = 90 * 24 * 3600
export const CLOCK_SKEW = 300
export const MAX_MODS = 64
export const MAX_FILES_PER_MOD = 512
export const MAX_TOTAL_BYTES = 256 * 1024 * 1024
export const MAX_JSON_DEPTH = 32
export const MAX_WIRE_BYTES = 256 * 1024
export const MAX_CRL_ENTRIES = 10_000
const MAX_SAFE = Number.MAX_SAFE_INTEGER // 2^53 - 1

const DOMAIN = {
  cert: 'fab-signing-cert-v1\n',
  crl: 'fab-crl-v1\n',
  manifest: 'fab-workspace-manifest-v1\n',
} as const
type Kind = keyof typeof DOMAIN

const SHA256 = /^[0-9a-f]{64}$/
const KID = /^[0-9a-f]{32}$/
const NAME = /^[a-z0-9][a-z0-9._-]{0,63}$/
const ID = /^[A-Za-z0-9_-]{1,64}$/
const VERSION = /^[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$/
const LABEL = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/
const RESERVED = new Set(['con', 'prn', 'aux', 'nul'])
for (const d of ['com', 'lpt']) for (let i = 1; i <= 9; i++) RESERVED.add(`${d}${i}`)
const BAD_PATH_CHARS = new Set('<>"|?*:\\')

// Characters Python's str.strip()/isspace() treat as white space (JS trim() differs).
const PY_SPACE = new Set(
  [
    0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680,
    0x2028, 0x2029, 0x202f, 0x205f, 0x3000,
    ...Array.from({ length: 11 }, (_, i) => 0x2000 + i),
  ].map((c) => String.fromCharCode(c)),
)

export class ManifestError extends Error {
  code: string
  state?: ClientState
  constructor(code: string, state?: ClientState) {
    super(code)
    this.code = code
    this.state = state
  }
}

type Json = null | boolean | number | string | Json[] | { [k: string]: Json }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Obj = Record<string, any>

const isInt = (x: unknown): x is number => typeof x === 'number' && Number.isInteger(x)
const isObj = (x: unknown): x is Obj =>
  typeof x === 'object' && x !== null && !Array.isArray(x)
const v1 = (x: unknown) => x === 1

function only(d: unknown, allowed: string[], code = 'malformed'): Obj {
  if (!isObj(d) || Object.keys(d).some((k) => !allowed.includes(k))) {
    throw new ManifestError(code)
  }
  return d
}

// ── strict JSON ──────────────────────────────────────────────────────────────

function hasLoneSurrogate(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i)
    if (c >= 0xd800 && c <= 0xdbff) {
      const n = s.charCodeAt(i + 1)
      if (n >= 0xdc00 && n <= 0xdfff) i++
      else return true
    } else if (c >= 0xdc00 && c <= 0xdfff) return true
  }
  return false
}

function checkJson(o: unknown, depth = 0): void {
  if (depth > MAX_JSON_DEPTH) throw new ManifestError('too_deep')
  if (o === null || typeof o === 'boolean') return
  if (typeof o === 'string') {
    if (hasLoneSurrogate(o)) throw new ManifestError('bad_string')
    return
  }
  if (typeof o === 'number') {
    if (Object.is(o, -0)) throw new ManifestError('unsupported_type')
    if (!Number.isInteger(o) || Math.abs(o) > MAX_SAFE) {
      throw new ManifestError(Number.isInteger(o) ? 'int_out_of_range' : 'unsupported_type')
    }
    return
  }
  if (Array.isArray(o)) {
    for (const v of o) checkJson(v, depth + 1)
    return
  }
  if (isObj(o)) {
    for (const [k, v] of Object.entries(o)) {
      if (hasLoneSurrogate(k)) throw new ManifestError('bad_string')
      checkJson(v, depth + 1)
    }
    return
  }
  throw new ManifestError('unsupported_type')
}

function esc(s: string): string {
  let out = '"'
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i)
    if (c === 0x22) out += '\\"'
    else if (c === 0x5c) out += '\\\\'
    else if (c === 0x08) out += '\\b'
    else if (c === 0x09) out += '\\t'
    else if (c === 0x0a) out += '\\n'
    else if (c === 0x0c) out += '\\f'
    else if (c === 0x0d) out += '\\r'
    else if (c >= 0x20 && c <= 0x7e) out += s[i]
    else out += '\\u' + c.toString(16).padStart(4, '0')
  }
  return out + '"'
}

function ser(o: unknown): string {
  if (o === null) return 'null'
  if (o === true) return 'true'
  if (o === false) return 'false'
  if (typeof o === 'string') return esc(o)
  if (typeof o === 'number') return String(o)
  if (Array.isArray(o)) return '[' + o.map(ser).join(',') + ']'
  // Default JS string comparison is UTF-16 code unit order (RFC 8785).
  const keys = Object.keys(o as Obj).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
  return '{' + keys.map((k) => esc(k) + ':' + ser((o as Obj)[k])).join(',') + '}'
}

export function canonicalBytes(o: unknown): Buffer {
  checkJson(o)
  return Buffer.from(ser(o), 'ascii')
}

export function digest(payload: unknown): string {
  return createHash('sha256').update(canonicalBytes(payload)).digest('hex')
}

/** Strict parser: size cap, duplicate keys, floats/exponents, `-0`, NaN/Infinity,
 * integers beyond +/-(2^53-1), lone surrogates and nesting beyond the profile. */
export function parseWire(data: string | Uint8Array, maxBytes = MAX_WIRE_BYTES): Json {
  const raw = typeof data === 'string' ? Buffer.from(data, 'utf8') : Buffer.from(data)
  if (raw.length > maxBytes) throw new ManifestError('wire_too_large')
  // A string that cannot be encoded as UTF-8 (a raw lone surrogate) is refused, never repaired.
  // (Encoded, a lone surrogate is 3 bytes either way, so the size check above agrees with Python.)
  if (typeof data === 'string' && hasLoneSurrogate(data)) throw new ManifestError('bad_encoding')
  let text: string
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw)
  } catch {
    throw new ManifestError('bad_encoding')
  }
  let i = 0
  const NUMBER = /-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/y
  const bad = () => new ManifestError('bad_json')
  const ws = () => {
    while (i < text.length && ' \t\n\r'.includes(text[i]!)) i++
  }

  // Nesting beyond the profile (32) is reported after the parse, like Python, so a fault that
  // comes first in reading order wins; this cap only keeps the recursion bounded.
  const RECURSION_CAP = 500

  function value(depth: number): Json {
    if (depth > RECURSION_CAP) throw new ManifestError('too_deep')
    ws()
    const c = text[i]
    if (c === '{') return object(depth)
    if (c === '[') return array(depth)
    if (c === '"') return string()
    if (c === 't' && text.startsWith('true', i)) return ((i += 4), true)
    if (c === 'f' && text.startsWith('false', i)) return ((i += 5), false)
    if (c === 'n' && text.startsWith('null', i)) return ((i += 4), null)
    if (text.startsWith('NaN', i) || text.startsWith('Infinity', i) || text.startsWith('-Infinity', i)) {
      throw new ManifestError('float_not_allowed')
    }
    return number()
  }

  function number(): number {
    NUMBER.lastIndex = i
    const m = NUMBER.exec(text)
    if (!m) throw bad()
    i += m[0].length
    if (m[2] !== undefined || m[3] !== undefined) throw new ManifestError('float_not_allowed')
    if (m[0] === '-0') throw new ManifestError('negative_zero')
    if (m[0].length > 17) throw new ManifestError('int_out_of_range')
    return Number(m[0])
  }

  function string(): string {
    i++ // opening quote
    let out = ''
    for (;;) {
      if (i >= text.length) throw bad()
      const c = text[i]!
      if (c === '"') {
        i++
        return out
      }
      if (c.charCodeAt(0) < 0x20) throw bad()
      if (c !== '\\') {
        out += c
        i++
        continue
      }
      const e = text[i + 1]
      i += 2
      const simple: Record<string, string> = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' }
      if (e !== undefined && Object.hasOwn(simple, e)) out += simple[e]
      else if (e === 'u') {
        const hex = text.slice(i, i + 4)
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) throw bad()
        out += String.fromCharCode(parseInt(hex, 16))
        i += 4
      } else throw bad()
    }
  }

  function array(depth: number): Json[] {
    i++
    const out: Json[] = []
    ws()
    if (text[i] === ']') return (i++, out)
    for (;;) {
      out.push(value(depth + 1))
      ws()
      if (text[i] === ',') {
        i++
        continue
      }
      if (text[i] === ']') return (i++, out)
      throw bad()
    }
  }

  function object(depth: number): { [k: string]: Json } {
    i++
    const out: { [k: string]: Json } = Object.create(null)
    let duplicate = false
    ws()
    if (text[i] === '}') return (i++, out)
    for (;;) {
      ws()
      if (text[i] !== '"') throw bad()
      const k = string()
      ws()
      if (text[i] !== ':') throw bad()
      i++
      const v = value(depth + 1)
      if (Object.hasOwn(out, k)) duplicate = true // reported when the object closes, as Python does
      out[k] = v
      ws()
      if (text[i] === ',') {
        i++
        continue
      }
      if (text[i] === '}') {
        i++
        if (duplicate) throw new ManifestError('duplicate_key')
        return out
      }
      throw bad()
    }
  }

  const result = value(0)
  ws()
  if (i !== text.length) throw bad()
  checkJson(result)
  return result
}

// ── keys and signatures ──────────────────────────────────────────────────────

const B64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/
/** Canonical standard base64 only: alphabet, padding, and no spare bits, so one byte string
 * has exactly one accepted spelling (same rule as the Python verifier). */
function b64(s: unknown): Buffer | null {
  if (typeof s !== 'string' || !B64.test(s)) return null
  const raw = Buffer.from(s, 'base64')
  return raw.toString('base64') === s ? raw : null
}

export function keyId(publicB64: string): string {
  const raw = b64(publicB64)
  if (!raw) throw new ManifestError('bad_key')
  return createHash('sha256').update(raw).digest('hex').slice(0, 32)
}

const SPKI_PREFIX = Buffer.from('302a300506032b6570032100', 'hex')

function verifySig(publicB64: unknown, kind: Kind, payload: unknown, sig: unknown): void {
  const message = Buffer.concat([Buffer.from(DOMAIN[kind], 'ascii'), canonicalBytes(payload)])
  const pub = b64(publicB64)
  const sg = b64(sig)
  let ok = false
  if (pub && sg && pub.length === 32 && sg.length === 64) {
    try {
      const key = createPublicKey({ key: Buffer.concat([SPKI_PREFIX, pub]), format: 'der', type: 'spki' })
      ok = edVerify(null, message, key, sg)
    } catch {
      ok = false
    }
  }
  if (!ok) throw new ManifestError('bad_signature')
}

/** Detached Ed25519 check for other signed documents that reuse the same canonical JSON and
 * strict key encoding (ADR-0031). The domain string keeps a signature of one kind from ever
 * being accepted as another. Returns false for every malformed input; it never throws. */
export function verifyDetached(publicB64: unknown, domain: string, payload: unknown, sig: unknown): boolean {
  try {
    const message = Buffer.concat([Buffer.from(domain, 'ascii'), canonicalBytes(payload)])
    const pub = b64(publicB64)
    const sg = b64(sig)
    if (!pub || !sg || pub.length !== 32 || sg.length !== 64) return false
    const key = createPublicKey({ key: Buffer.concat([SPKI_PREFIX, pub]), format: 'der', type: 'spki' })
    return edVerify(null, message, key, sg)
  } catch {
    return false
  }
}

// ── body validation (same rules as the server) ───────────────────────────────

const BODY_KEYS = ['typ', 'v', 'epoch', 'company_id', 'person_id', 'aud', 'generation', 'issued_at', 'expires_at', 'min_client_version', 'gateway_url', 'layout', 'mods']
const CERT_KEYS = ['typ', 'v', 'kid', 'pub', 'issuer_kid', 'not_before', 'not_after', 'serial', 'epoch']
const CRL_KEYS = ['typ', 'v', 'number', 'revoked_kids', 'issued_at', 'next_update']

function checkName(name: unknown): string {
  if (typeof name !== 'string' || !NAME.test(name) || name.endsWith('.') || RESERVED.has(name.split('.')[0]!)) {
    throw new ManifestError('bad_name')
  }
  return name
}

const codePoints = (s: string) => Array.from(s).length
const PATH_PART = /^[A-Za-z0-9._@+-]{1,255}$/

/** Portable path profile (ASCII letters, digits and `. _ @ + -`); see the Python docstring. */
function safePath(path: unknown): string {
  if (typeof path !== 'string' || path === '' || path.length > 200 || path.startsWith('/')) {
    throw new ManifestError('bad_path')
  }
  for (const part of path.split('/')) {
    if (
      part === '' || part === '.' || part === '..' ||
      !PATH_PART.test(part) ||
      part.endsWith('.') ||
      RESERVED.has(part.split('.')[0]!.toLowerCase())
    ) {
      throw new ManifestError('bad_path')
    }
  }
  return path
}

function checkHttpsUrl(url: unknown): void {
  const bad = () => new ManifestError('bad_gateway_url')
  if (typeof url !== 'string' || codePoints(url) > 300) throw bad()
  if (Array.from(url).some((c) => PY_SPACE.has(c) || c.codePointAt(0)! < 0x20)) throw bad()
  const m = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#]*)([^]*)$/.exec(url)
  if (!m) throw bad()
  const [, scheme, authority, rest] = m
  if (scheme!.toLowerCase() !== 'https') throw bad()
  if (authority!.includes('@')) throw bad() // userinfo
  if (authority!.startsWith('[')) throw bad() // an IP literal is not a hostname here
  let host = authority!
  let port: string | undefined
  const colon = authority!.lastIndexOf(':')
  if (colon !== -1) {
    host = authority!.slice(0, colon)
    port = authority!.slice(colon + 1)
  }
  if (port !== undefined && port !== '') {
    if (!/^[0-9]+$/.test(port)) throw bad()
    const n = Number(port)
    if (!(n > 0 && n < 65536)) throw bad()
  }
  if (host === '' || host.length > 253 || !host.split('.').every((l) => LABEL.test(l))) throw bad()
  const hash = rest!.indexOf('#')
  if (hash !== -1 && rest!.slice(hash + 1) !== '') throw bad()
}

export function validateBody(p: unknown): void {
  const b = only(p, BODY_KEYS)
  if (!isInt(b.epoch) || b.epoch < 1) throw new ManifestError('bad_epoch')
  for (const k of ['company_id', 'person_id']) {
    if (typeof b[k] !== 'string' || !ID.test(b[k])) throw new ManifestError('bad_binding')
  }
  if (typeof b.aud !== 'string' || !NAME.test(b.aud)) throw new ManifestError('bad_binding')
  if (!isInt(b.generation) || b.generation < 1) throw new ManifestError('bad_generation')
  for (const k of ['issued_at', 'expires_at']) {
    if (!isInt(b[k]) || b[k] < 0) throw new ManifestError('bad_time')
  }
  const life = b.expires_at - b.issued_at
  if (!(life > 0 && life <= MAX_MANIFEST_LIFETIME)) throw new ManifestError('bad_lifetime')
  if (typeof b.min_client_version !== 'string' || !VERSION.test(b.min_client_version)) throw new ManifestError('bad_version')
  checkHttpsUrl(b.gateway_url)

  const layout = only(b.layout, ['id', 'sha256', 'size'], 'bad_layout')
  checkName(layout.id)
  if (typeof layout.sha256 !== 'string' || !SHA256.test(layout.sha256)) throw new ManifestError('bad_layout')
  if (!isInt(layout.size) || layout.size < 0) throw new ManifestError('bad_size')
  let total: number = layout.size

  if (!Array.isArray(b.mods) || b.mods.length > MAX_MODS) throw new ManifestError('bad_mods')
  const seenMods = new Set<string>()
  for (const m of b.mods) {
    only(m, ['name', 'version', 'files'], 'bad_mod')
    const name = checkName(m.name)
    if (seenMods.has(name)) throw new ManifestError('duplicate_mod')
    seenMods.add(name)
    if (typeof m.version !== 'string' || !VERSION.test(m.version)) throw new ManifestError('bad_mod')
    if (!Array.isArray(m.files) || m.files.length === 0 || m.files.length > MAX_FILES_PER_MOD) {
      throw new ManifestError('bad_mod_files')
    }
    const keys = new Set<string>()
    for (const f of m.files) {
      only(f, ['path', 'sha256', 'size'], 'bad_mod_files')
      const path = safePath(f.path)
      const key = path.toLowerCase()
      if (keys.has(key)) throw new ManifestError('duplicate_path')
      keys.add(key)
      if (typeof f.sha256 !== 'string' || !SHA256.test(f.sha256)) throw new ManifestError('bad_hash')
      if (!isInt(f.size) || f.size < 0) throw new ManifestError('bad_size')
      total += f.size
    }
    for (const key of keys) {
      const parts = key.split('/')
      for (let i = 1; i < parts.length; i++) {
        if (keys.has(parts.slice(0, i).join('/'))) throw new ManifestError('path_conflict')
      }
    }
  }
  if (total > MAX_TOTAL_BYTES) throw new ManifestError('too_large')
}

// ── client state ─────────────────────────────────────────────────────────────

export interface Expected {
  company_id: string
  person_id: string
  aud: string
  client_version?: string
  min_generation?: number | null
  min_epoch?: number | null
  min_crl_number?: number | null
}

export interface ClientState {
  generations: Record<string, { generation: number; digest: string }>
  epoch: number
  crl_number: number
  crl_digest: string
  crl_next_update: number
  revoked: string[]
  last_seen: number
  signing_kid: string
}

export const emptyState = (): ClientState => ({
  generations: {}, epoch: 0, crl_number: 0, crl_digest: '', crl_next_update: 0, revoked: [], last_seen: 0, signing_kid: '',
})

const vtuple = (v: string) => v.split('.').map(Number)
function versionLess(a: string, b: string): boolean {
  const x = vtuple(a)
  const y = vtuple(b)
  for (let i = 0; i < 3; i++) if (x[i]! !== y[i]!) return x[i]! < y[i]!
  return false
}

const bindingKey = (company: string, person: string) => JSON.stringify([company, person])

function checkClock(now: unknown, state: ClientState): ClientState {
  if (!isInt(now) || now < 0) throw new ManifestError('bad_clock')
  if (now + CLOCK_SKEW < state.last_seen) throw new ManifestError('clock_rollback', state)
  return { ...state, last_seen: Math.max(state.last_seen, now) }
}

// ── certificate, CRL, manifest ───────────────────────────────────────────────

export function checkCertificate(cert: unknown, rootPub: string, now: number): Obj {
  only(cert, ['payload', 'sig'], 'bad_cert')
  const c = cert as Obj
  const cp = only(c.payload, CERT_KEYS, 'bad_cert')
  if (cp.typ !== 'fab-signing-cert' || !v1(cp.v)) throw new ManifestError('bad_cert')
  verifySig(rootPub, 'cert', cp, c.sig ?? '')
  if (cp.issuer_kid !== keyId(rootPub)) throw new ManifestError('bad_cert')
  if (typeof cp.pub !== 'string' || cp.kid !== keyId(cp.pub)) throw new ManifestError('bad_cert')
  const { not_before: nb, not_after: na, epoch } = cp
  if (!(isInt(nb) && isInt(na) && isInt(epoch) && isInt(cp.serial))) throw new ManifestError('bad_cert')
  if (!(na - nb > 0 && na - nb <= MAX_CERT_LIFETIME) || epoch < 1) throw new ManifestError('bad_cert')
  if (now + CLOCK_SKEW < nb || now - CLOCK_SKEW > na) throw new ManifestError('cert_not_valid_now')
  return cp
}

export function verifyCrl(crl: unknown, rootPub: string, state: ClientState, now: number): ClientState {
  only(crl, ['payload', 'sig'], 'bad_crl')
  const c = crl as Obj
  const p = only(c.payload, CRL_KEYS, 'bad_crl')
  if (p.typ !== 'fab-crl' || !v1(p.v)) throw new ManifestError('bad_crl')
  verifySig(rootPub, 'crl', p, c.sig ?? '')
  const kids = p.revoked_kids
  const sorted = Array.isArray(kids) ? [...new Set<string>(kids)].sort() : []
  if (
    !isInt(p.number) || p.number < 1 || !isInt(p.issued_at) || !isInt(p.next_update) ||
    p.next_update <= p.issued_at || !Array.isArray(kids) || kids.length > MAX_CRL_ENTRIES ||
    kids.length !== sorted.length || kids.some((k: unknown, i: number) => k !== sorted[i]) ||
    !kids.every((k: unknown) => typeof k === 'string' && KID.test(k))
  ) {
    throw new ManifestError('bad_crl')
  }
  state = checkClock(now, state)
  if (p.issued_at > now + CLOCK_SKEW) throw new ManifestError('crl_from_future', state)
  const d = digest(p)
  if (p.number < state.crl_number) throw new ManifestError('crl_rollback', state)
  if (p.number === state.crl_number) {
    if (d !== state.crl_digest) throw new ManifestError('crl_conflict', state)
    return state
  }
  if (!state.revoked.every((k) => kids.includes(k))) throw new ManifestError('crl_not_cumulative', state)
  return { ...state, crl_number: p.number, crl_digest: d, crl_next_update: p.next_update, revoked: kids }
}

export interface VerifyOptions {
  rootPub: string
  expected: Expected
  now: number
  state: ClientState
  crl?: unknown
  requireCrl?: boolean
}

function verifyInner(envelope: unknown, o: VerifyOptions, state: ClientState): [Obj, ClientState] {
  const { rootPub, expected, now } = o
  const clientVersion = expected.client_version === undefined ? '0.0.0' : expected.client_version
  if (typeof clientVersion !== 'string' || !VERSION.test(clientVersion)) {
    throw new ManifestError('bad_client_version')
  }
  const env = only(envelope, ['cert', 'payload', 'sig'])
  const payload = env.payload
  if (!isObj(payload)) throw new ManifestError('malformed')
  const cp = checkCertificate(env.cert, rootPub, now)
  const epoch: number = cp.epoch
  if (state.revoked.includes(cp.kid)) throw new ManifestError('cert_revoked')
  if (o.requireCrl) {
    if (state.crl_number < 1) throw new ManifestError('crl_required')
    if (now - CLOCK_SKEW > state.crl_next_update) throw new ManifestError('crl_stale')
  }
  if (epoch < state.epoch) throw new ManifestError('epoch_rollback')
  if (epoch > state.epoch && state.signing_kid && cp.kid === state.signing_kid) {
    throw new ManifestError('epoch_needs_new_key')
  }

  if (payload.typ !== 'fab-workspace-manifest' || !v1(payload.v)) throw new ManifestError('malformed')
  verifySig(cp.pub, 'manifest', payload, env.sig ?? '')
  validateBody(payload)
  if (payload.epoch !== epoch) throw new ManifestError('epoch_mismatch')

  if (payload.company_id !== expected.company_id || payload.person_id !== expected.person_id || payload.aud !== expected.aud) {
    throw new ManifestError('wrong_binding')
  }
  if (versionLess(clientVersion, payload.min_client_version)) throw new ManifestError('client_too_old')
  if (now + CLOCK_SKEW < payload.issued_at) throw new ManifestError('not_yet_valid')
  if (now - CLOCK_SKEW > payload.expires_at) throw new ManifestError('expired')
  if (payload.issued_at < cp.not_before || payload.expires_at > cp.not_after) throw new ManifestError('outside_cert_window')

  const key = bindingKey(payload.company_id, payload.person_id)
  const mg = expected.min_generation ?? null
  const me = expected.min_epoch ?? null
  const mc = expected.min_crl_number ?? null
  if (state.epoch === 0 || !Object.hasOwn(state.generations, key)) {
    if (mg === null || me === null || mc === null) throw new ManifestError('bootstrap_floor_required')
  }
  if (me !== null && epoch < me) throw new ManifestError('epoch_rollback')
  if (mg !== null && payload.generation < mg) throw new ManifestError('below_floor')
  if (mc !== null && state.crl_number < mc) throw new ManifestError('crl_below_floor')

  let gens = state.generations
  if (epoch > state.epoch) gens = {}
  const d = digest(payload)
  const last = gens[key]
  if (last) {
    if (payload.generation < last.generation) throw new ManifestError('rollback')
    if (payload.generation === last.generation && d !== last.digest) throw new ManifestError('generation_conflict')
  }
  gens = { ...gens, [key]: { generation: payload.generation, digest: d } }
  return [payload, { ...state, generations: gens, epoch: Math.max(epoch, state.epoch), signing_kid: cp.kid }]
}

/** Returns `[payload, newState]` or throws ManifestError (its `.state` is the state
 * reached so far: persist it even on failure, a revocation list may have been taken). */
export function verifyManifest(envelope: unknown, o: VerifyOptions): [Obj, ClientState] {
  let state = o.state
  try {
    state = checkClock(o.now, state)
    if (o.crl !== undefined && o.crl !== null) state = verifyCrl(o.crl, o.rootPub, state, o.now)
    return verifyInner(envelope, o, state)
  } catch (e) {
    if (e instanceof ManifestError && e.state === undefined) e.state = state
    throw e
  }
}

/** `verifyManifest` for untrusted bytes. */
export function verifyWire(data: string | Uint8Array, o: VerifyOptions): [Obj, ClientState] {
  return verifyManifest(parseWire(data), o)
}

/** Check one downloaded file against its manifest entry before staging it. */
export function verifyFile(content: Uint8Array, entry: { size: number; sha256: string }): void {
  if (content.length !== entry.size) throw new ManifestError('size_mismatch')
  if (createHash('sha256').update(content).digest('hex') !== entry.sha256) throw new ManifestError('hash_mismatch')
}
