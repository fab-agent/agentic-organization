/**
 * Verify the Ed25519 signature on the org's opencode config bundle served at
 * `/.well-known/opencode` (ADR-0011). `3pa` pins the key on first use and
 * refuses to launch a bundle whose signature does not verify (ADR-0009).
 *
 * The backend signs `canonical(config)` where canonical == Python
 * `json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
 * — see `backend/services/wellknown_sign.py`. `canonicalize()` here must produce
 * byte-identical output.
 */

import { createPublicKey, verify } from 'node:crypto'

export interface WellKnownBundle {
  config: unknown
  signature: string
  key_id: string
  algorithm: string
  issued_at?: string
}

/** Recursively sort object keys, then stringify with no whitespace. */
export function canonicalize(value: unknown): string {
  return JSON.stringify(sortDeep(value))
}

function sortDeep(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortDeep)
  if (v && typeof v === 'object') {
    const out: Record<string, unknown> = {}
    for (const k of Object.keys(v as Record<string, unknown>).sort()) {
      out[k] = sortDeep((v as Record<string, unknown>)[k])
    }
    return out
  }
  return v
}

// SPKI DER prefix for a raw 32-byte Ed25519 public key.
const SPKI_ED25519_PREFIX = Buffer.from('302a300506032b6570032100', 'hex')

export function ed25519PublicKeyFromRaw(rawB64: string) {
  const raw = Buffer.from(rawB64, 'base64')
  if (raw.length !== 32) {
    throw new Error(`ed25519 public key must be 32 bytes, got ${raw.length}`)
  }
  return createPublicKey({
    key: Buffer.concat([SPKI_ED25519_PREFIX, raw]),
    format: 'der',
    type: 'spki',
  })
}

export function verifyConfigSignature(opts: {
  config: unknown
  signatureB64: string
  publicKeyB64: string
}): boolean {
  try {
    const key = ed25519PublicKeyFromRaw(opts.publicKeyB64)
    const msg = Buffer.from(canonicalize(opts.config), 'utf8')
    const sig = Buffer.from(opts.signatureB64, 'base64')
    return verify(null, msg, key, sig)
  } catch {
    return false
  }
}

/**
 * Fetch `/.well-known/opencode` + its public key, verify the signature, and
 * (TOFU) check the key id against the one pinned last time.
 *
 * `pinnedKeyId` is the value stored in the session on a previous run (or null on
 * the first). Returns the bundle + the key id to persist. Throws on a bad
 * signature or a key rotation the caller has not accepted.
 */
export async function fetchAndVerifyWellKnown(
  baseUrl: string,
  pinnedKeyId: string | null,
  opts: { allowKeyChange?: boolean; fetchImpl?: typeof fetch } = {},
): Promise<{ bundle: WellKnownBundle; keyId: string; publicKeyB64: string }> {
  const f = opts.fetchImpl ?? fetch
  const [bundleRes, pubRes] = await Promise.all([
    f(`${baseUrl}/.well-known/opencode`),
    f(`${baseUrl}/.well-known/opencode/pubkey`),
  ])
  if (!bundleRes.ok) throw new Error(`/.well-known/opencode → ${bundleRes.status}`)
  if (!pubRes.ok) throw new Error(`/.well-known/opencode/pubkey → ${pubRes.status}`)

  const bundle = (await bundleRes.json()) as WellKnownBundle
  const pub = (await pubRes.json()) as {
    public_key_b64: string
    key_id: string
    previous_key_id?: string | null
  }

  const ok = verifyConfigSignature({
    config: bundle.config,
    signatureB64: bundle.signature,
    publicKeyB64: pub.public_key_b64,
  })
  if (!ok) throw new Error('config signature does not verify — refusing to launch')

  if (pinnedKeyId && pinnedKeyId !== pub.key_id) {
    // A rotation the server advertises (pinned key == previous_key_id) is
    // accepted automatically and re-pinned; anything else needs --accept-key-change.
    const isAdvertisedRotation = pinnedKeyId === pub.previous_key_id
    if (!isAdvertisedRotation && !opts.allowKeyChange) {
      throw new Error(
        `signing key changed (pinned ${pinnedKeyId}, server ${pub.key_id}). ` +
          'Re-run with --accept-key-change if this rotation is expected.',
      )
    }
  }

  return { bundle, keyId: pub.key_id, publicKeyB64: pub.public_key_b64 }
}
