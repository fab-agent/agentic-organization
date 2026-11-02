import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  type ClientState,
  type Expected,
  ManifestError,
  canonicalBytes,
  digest,
  emptyState,
  keyId,
  parseWire,
  verifyFile,
  verifyWire,
} from '../src/utils/workspace-manifest.ts'

// The vectors are produced by the Python implementation (backend/tests/test_workspace_manifest.py)
// and are the contract between the two: same bytes, same signatures, same verdicts.
const here = dirname(fileURLToPath(import.meta.url))
const vectors = JSON.parse(
  readFileSync(join(here, '..', '..', '..', 'backend', 'tests', 'vectors', 'workspace_manifest_vectors.json'), 'utf8'),
)

test('canonical bytes are identical to Python for every vector', () => {
  for (const c of vectors.canonical) {
    assert.equal(canonicalBytes(c.input).toString('ascii'), c.bytes, JSON.stringify(c.input))
  }
})

test('keys sort by UTF-16 code unit, like Python after the profile change', () => {
  assert.equal(
    canonicalBytes({ '': 1, '\u{10000}': 2 }).toString('ascii'),
    '{"\\ud800\\udc00":2,"\\ue000":1}',
  )
})

test('the strict wire parser rejects what the profile forbids', () => {
  for (const text of vectors.reject_wire) {
    assert.throws(() => parseWire(text), ManifestError, text)
  }
  assert.throws(() => parseWire('{"a":' + '9'.repeat(5000) + '}'), (e: ManifestError) => e.code === 'int_out_of_range')
  assert.throws(() => parseWire('{"__proto__":1,"__proto__":2}'), (e: ManifestError) => e.code === 'duplicate_key')
})

test('__proto__ keys are data, never a prototype', () => {
  const o = parseWire('{"__proto__":{"polluted":true}}') as Record<string, unknown>
  assert.equal(({} as Record<string, unknown>).polluted, undefined)
  assert.deepEqual(Object.keys(o), ['__proto__'])
})

test('the manifest digest matches Python', () => {
  assert.equal(digest(vectors.manifest.payload), vectors.manifest_digest)
})

test('key ids are recomputed from the public key', () => {
  assert.equal(keyId(vectors.signing_pub), vectors.cert.payload.kid)
  assert.throws(() => keyId('not base64!'), (e: ManifestError) => e.code === 'bad_key')
})

function runCase(c: (typeof vectors.verify_cases)[number]) {
  const expected: Expected = c.expected
  try {
    const [payload, state] = verifyWire(c.wire, {
      rootPub: vectors.root_pub,
      expected,
      now: c.now,
      state: structuredClone(c.state) as ClientState,
      crl: c.crl,
      requireCrl: c.require_crl,
    })
    return { ok: true, generation: payload.generation, state }
  } catch (e) {
    if (e instanceof ManifestError) return { ok: false, code: e.code }
    throw e
  }
}

for (const c of vectors.verify_cases) {
  test(`parity: ${c.name}`, () => {
    const got = runCase(c)
    assert.deepEqual(got, c.result)
  })
}

test('parity covers success, failure and every state-changing path', () => {
  const codes = new Set(vectors.verify_cases.map((c: { result: { code?: string } }) => c.result.code))
  for (const must of ['bad_signature', 'rollback', 'epoch_needs_new_key', 'crl_not_cumulative', 'bootstrap_floor_required', 'duplicate_key']) {
    assert.ok(codes.has(must), `no case produces ${must}`)
  }
  assert.ok(vectors.verify_cases.some((c: { result: { ok: boolean } }) => c.result.ok))
})

test('a failed verification still reports the state reached (a revocation list is kept)', () => {
  const c = vectors.verify_cases.find((x: { name: string }) => x.name === 'revoked_key')
  try {
    verifyWire(c.wire, {
      rootPub: vectors.root_pub,
      expected: c.expected,
      now: c.now,
      state: emptyState(),
      crl: c.crl,
    })
    assert.fail('should have thrown')
  } catch (e) {
    assert.ok(e instanceof ManifestError)
    assert.equal(e.code, 'cert_revoked')
    assert.equal(e.state?.crl_number, 1)
    assert.equal(e.state?.revoked.length, 1)
  }
})

test('verifyFile checks size and hash', () => {
  const data = Buffer.from('console.log(1)')
  const entry = { size: data.length, sha256: require_sha(data) }
  verifyFile(data, entry)
  assert.throws(() => verifyFile(Buffer.from('console.log(1) '), entry), (e: ManifestError) => e.code === 'size_mismatch')
  assert.throws(() => verifyFile(Buffer.from('console.log(2)'), entry), (e: ManifestError) => e.code === 'hash_mismatch')
})

import { createHash } from 'node:crypto'
function require_sha(b: Buffer): string {
  return createHash('sha256').update(b).digest('hex')
}
