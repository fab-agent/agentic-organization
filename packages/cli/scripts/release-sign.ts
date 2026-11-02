/**
 * Offline release signing (ADR-0031). Run on the machine that holds the release key; the key
 * never goes into CI.
 *
 *   npx tsx scripts/release-sign.ts keygen --out DIR
 *   npx tsx scripts/release-sign.ts sign   --key DIR/release.key --body body.json --out release.json
 *   npx tsx scripts/release-sign.ts verify --pub BASE64|FILE --file release.json
 *
 * body.json is the unsigned document (see docs/architecture/release-chain.md).
 */
import { createPrivateKey, createPublicKey, generateKeyPairSync, sign as edSign } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { RELEASE_DOMAIN, verifyRelease, emptyReleaseState } from '../src/utils/release.js'
import { canonicalBytes, keyId } from '../src/utils/workspace-manifest.js'

const [, , cmd, ...args] = process.argv
const flag = (n: string) => { const i = args.indexOf(n); return i !== -1 ? args[i + 1] : undefined }
const die = (m: string): never => { console.error(m); process.exit(1) }

if (cmd === 'keygen') {
  const out = flag('--out') ?? die('--out DIR is required')
  mkdirSync(out, { recursive: true, mode: 0o700 })
  const keyPath = join(out, 'release.key')
  if (existsSync(keyPath)) die(`${keyPath} already exists; refusing to overwrite a release key`)
  const { privateKey, publicKey } = generateKeyPairSync('ed25519')
  writeFileSync(keyPath, privateKey.export({ type: 'pkcs8', format: 'pem' }), { mode: 0o600, flag: 'wx' })
  const raw = (publicKey.export({ type: 'spki', format: 'der' }) as Buffer).subarray(-32).toString('base64')
  writeFileSync(join(out, 'release.pub'), raw + '\n')
  console.log(`public key (give this to installers): ${raw}\nkey id: ${keyId(raw)}`)
} else if (cmd === 'sign') {
  const body = JSON.parse(readFileSync(flag('--body') ?? die('--body is required'), 'utf8'))
  const key = createPrivateKey(readFileSync(flag('--key') ?? die('--key is required')))
  const pub = (createPublicKey(key).export({ type: 'spki', format: 'der' }) as Buffer).subarray(-32).toString('base64')
  const sig = edSign(null, Buffer.concat([Buffer.from(RELEASE_DOMAIN, 'ascii'), canonicalBytes(body)]), key).toString('base64')
  const doc = JSON.stringify({ body, kid: keyId(pub), sig }, null, 2) + '\n'
  // refuse to emit something this client would not accept
  verifyRelease(doc, { pub, now: Math.floor(Date.now() / 1000), state: emptyReleaseState() })
  writeFileSync(flag('--out') ?? die('--out is required'), doc)
  console.log('signed; verified against its own key')
} else if (cmd === 'verify') {
  const p = flag('--pub') ?? die('--pub is required')
  const pub = existsSync(p) ? readFileSync(p, 'utf8').trim() : p
  const r = verifyRelease(readFileSync(flag('--file') ?? die('--file is required')), { pub, now: Math.floor(Date.now() / 1000), state: emptyReleaseState() })
  console.log(`valid: ${r.body.channel} ${r.body.version} seq ${r.body.seq}, ${r.body.artifacts.length} artifact(s), digest ${r.digest}`)
} else {
  die('usage: release-sign.ts keygen|sign|verify (see the header of this file)')
}
