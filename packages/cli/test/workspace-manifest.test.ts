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


test('a string input with a raw lone surrogate is refused, not repaired', () => {
  assert.throws(() => parseWire('{"a":"\ud800"}'), (e: ManifestError) => e.code === 'bad_encoding')
  // the escape spelling is a different fault, and a proper pair is fine
  assert.throws(() => parseWire('{"a":"\\ud800"}'), (e: ManifestError) => e.code === 'bad_string')
  assert.deepEqual(Object.entries(parseWire('{"a":"\\ud83d\\ude00"}') as object), [['a', '\u{1F600}']])
  assert.throws(() => parseWire(Buffer.from([0x7b, 0x22, 0xed, 0xa0, 0x80, 0x22, 0x7d])), (e: ManifestError) => e.code === 'bad_encoding')
})

test('negative zero has no canonical form even as a plain object', () => {
  assert.throws(() => canonicalBytes({ a: -0 }), (e: ManifestError) => e.code === 'unsupported_type')
  assert.equal(canonicalBytes({ a: 0 }).toString('ascii'), '{"a":0}')
})

test('base64 has exactly one accepted spelling', () => {
  for (const bad of ['AAAA=', 'AAAA====', 'Zh==', 'Zm9=', 'AA', 'A===', 'AAAA\n', ' AAAA', '-_-_']) {
    assert.throws(() => keyId(bad), (e: ManifestError) => e.code === 'bad_key', bad)
  }
  assert.equal(keyId('AAAAAAAA').length, 32)
})

test('the trusted client version must be well formed, and defaults to 0.0.0 when absent', () => {
  const c = vectors.verify_cases.find((x: { name: string }) => x.name === 'valid')
  const base = { rootPub: vectors.root_pub, now: c.now, state: emptyState() }
  const { client_version: _drop, ...rest } = c.expected
  assert.throws(() => verifyWire(c.wire, { ...base, expected: { ...rest, client_version: '1.0' } }), (e: ManifestError) => e.code === 'bad_client_version')
  // absent means 0.0.0, which is older than this manifest's minimum 1.0.0
  assert.throws(() => verifyWire(c.wire, { ...base, expected: rest }), (e: ManifestError) => e.code === 'client_too_old')
})

test('several faults in one document: the first in reading order decides, like Python', () => {
  const code = (text: string) => {
    try { parseWire(text) } catch (e) { return (e as ManifestError).code }
    return 'ok'
  }
  assert.equal(code('{"a":1,"a":2,"b":1.0}'), 'float_not_allowed')
  assert.equal(code('{"x":1,"x":2,'), 'bad_json')
  assert.equal(code('[' .repeat(40) + '1.0' + ']'.repeat(40)), 'float_not_allowed')
  assert.equal(code('[' .repeat(40) + '1' + ']'.repeat(40)), 'too_deep')
  assert.equal(code('{"a":1,"a":2}'), 'duplicate_key')
})


test('V5: an explicit null client_version is a malformed trusted value, not "absent"', () => {
  const c = vectors.verify_cases.find((x: { name: string }) => x.name === 'valid')
  const base = { rootPub: vectors.root_pub, now: c.now, state: emptyState() }
  for (const bad of [null, 5, true, {}, '']) {
    assert.throws(
      () => verifyWire(c.wire, { ...base, expected: { ...c.expected, client_version: bad as unknown as string } }),
      (e: ManifestError) => e.code === 'bad_client_version',
      String(bad),
    )
  }
})

test('V2: the size limit is checked before the encoding, like Python', () => {
  const big = '{"a":"\ud800' + 'x'.repeat(300_000) + '"}'
  assert.throws(() => parseWire(big), (e: ManifestError) => e.code === 'wire_too_large')
  assert.throws(() => parseWire('{"a":"\ud800"}'), (e: ManifestError) => e.code === 'bad_encoding')
})

test('records keyed by a name like "constructor" are data (own properties only)', () => {
  const c = vectors.verify_cases.find((x: { name: string }) => x.name === 'valid')
  const state = emptyState()
  // no history for any person: a prototype member must not count as history
  assert.throws(
    () => verifyWire(c.wire, { rootPub: vectors.root_pub, now: c.now, state, expected: { company_id: 'co1', person_id: 'p1', aud: 'herdr-provisioner', client_version: '1.0.0' } }),
    (e: ManifestError) => e.code === 'bootstrap_floor_required',
  )
})
