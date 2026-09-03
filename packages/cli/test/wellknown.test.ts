import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  canonicalize,
  ed25519PublicKeyFromRaw,
  fetchAndVerifyWellKnown,
  verifyConfigSignature,
} from '../src/utils/wellknown.ts'

const here = dirname(fileURLToPath(import.meta.url))
const fx = JSON.parse(readFileSync(join(here, 'wellknown.fixture.json'), 'utf8'))

test('canonicalize matches Python json.dumps(sort_keys, separators, ensure_ascii=False)', () => {
  assert.equal(canonicalize(fx.config), fx.canonical)
})

test('canonicalize sorts nested keys and preserves array order', () => {
  assert.equal(
    canonicalize({ b: 1, a: { d: [3, 1, 2], c: 4 } }),
    '{"a":{"c":4,"d":[3,1,2]},"b":1}',
  )
})

test('verifyConfigSignature accepts the real backend signature', () => {
  assert.equal(
    verifyConfigSignature({
      config: fx.config,
      signatureB64: fx.signature,
      publicKeyB64: fx.public_key_b64,
    }),
    true,
  )
})

test('verifyConfigSignature rejects a tampered config', () => {
  const tampered = { ...fx.config, 'x-fabagent': { fail_closed: false } }
  assert.equal(
    verifyConfigSignature({
      config: tampered,
      signatureB64: fx.signature,
      publicKeyB64: fx.public_key_b64,
    }),
    false,
  )
})

test('verifyConfigSignature rejects a wrong key', () => {
  assert.equal(
    verifyConfigSignature({
      config: fx.config,
      signatureB64: fx.signature,
      publicKeyB64: Buffer.alloc(32).toString('base64'),
    }),
    false,
  )
})

test('ed25519PublicKeyFromRaw rejects a non-32-byte key', () => {
  assert.throws(() => ed25519PublicKeyFromRaw(Buffer.alloc(16).toString('base64')))
})

test('fetchAndVerifyWellKnown pins the key on first use and rejects a bad signature', async () => {
  const bundle = {
    config: fx.config,
    signature: fx.signature,
    key_id: 'abc123',
    algorithm: 'ed25519',
  }
  const stub = (async (url: string) => {
    if (url.endsWith('/pubkey')) {
      return new Response(JSON.stringify({ public_key_b64: fx.public_key_b64, key_id: 'abc123' }))
    }
    return new Response(JSON.stringify(bundle))
  }) as unknown as typeof fetch

  const { keyId } = await fetchAndVerifyWellKnown('https://x', null, { fetchImpl: stub })
  assert.equal(keyId, 'abc123')

  // pinned to a different key, no override -> throws
  await assert.rejects(
    fetchAndVerifyWellKnown('https://x', 'OLDKEY', { fetchImpl: stub }),
    /signing key changed/,
  )
  // ...unless the change is accepted
  const okChange = await fetchAndVerifyWellKnown('https://x', 'OLDKEY', {
    fetchImpl: stub,
    allowKeyChange: true,
  })
  assert.equal(okChange.keyId, 'abc123')
})

test('fetchAndVerifyWellKnown auto-accepts an advertised rotation (pinned == previous_key_id)', async () => {
  const stub = (async (url: string) => {
    if (url.endsWith('/pubkey')) {
      return new Response(
        JSON.stringify({
          public_key_b64: fx.public_key_b64,
          key_id: 'newkey',
          previous_key_id: 'oldkey',
        }),
      )
    }
    return new Response(
      JSON.stringify({ config: fx.config, signature: fx.signature, key_id: 'newkey' }),
    )
  }) as unknown as typeof fetch

  // pinned to the key the server says it just rotated away from -> no error, re-pin
  const { keyId } = await fetchAndVerifyWellKnown('https://x', 'oldkey', { fetchImpl: stub })
  assert.equal(keyId, 'newkey')

  // pinned to some unrelated key -> still refused
  await assert.rejects(
    fetchAndVerifyWellKnown('https://x', 'unrelated', { fetchImpl: stub }),
    /signing key changed/,
  )
})

test('fetchAndVerifyWellKnown throws on a forged bundle', async () => {
  const stub = (async (url: string) => {
    if (url.endsWith('/pubkey')) {
      return new Response(
        JSON.stringify({ public_key_b64: Buffer.alloc(32).toString('base64'), key_id: 'z' }),
      )
    }
    return new Response(
      JSON.stringify({ config: fx.config, signature: fx.signature, key_id: 'z' }),
    )
  }) as unknown as typeof fetch

  await assert.rejects(
    fetchAndVerifyWellKnown('https://x', null, { fetchImpl: stub }),
    /signature does not verify/,
  )
})
