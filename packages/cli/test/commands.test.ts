import assert from 'node:assert/strict'
import { generateKeyPairSync, sign as nodeSign } from 'node:crypto'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

process.env.THREEPA_SESSION_FILE = join(
  mkdtempSync(join(tmpdir(), '3pa-cmd-')),
  'session.json',
)
writeFileSync(
  process.env.THREEPA_SESSION_FILE,
  JSON.stringify({
    base_url: 'https://x',
    token: 't',
    refresh_token: 'r',
    persona_id: 'p1',
    persona_name: 'Ada',
    saved_at: new Date().toISOString(),
  }),
)

const { pollCommands } = await import('../src/utils/commands.ts')
const { canonicalize } = await import('../src/utils/wellknown.ts')
const { loadSession } = await import('../src/commands/login.ts')

const { publicKey, privateKey } = generateKeyPairSync('ed25519')
const pubB64 = publicKey.export({ type: 'spki', format: 'der' }).subarray(-32).toString('base64')
const sign = (cmd: unknown) =>
  nodeSign(null, Buffer.from(canonicalize(cmd)), privateKey).toString('base64')

function cmd(kind: string, extra: Record<string, unknown> = {}) {
  return {
    id: 'c1',
    persona_id: 'p1',
    kind,
    payload: null,
    issued_by: 'user:u1',
    created_at: '2026-09-03T00:00:00',
    ...extra,
  }
}

function stubFetch(commands: { command: unknown; signature: string }[]) {
  const calls: string[] = []
  const f = (async (url: string) => {
    calls.push(url)
    if (url.endsWith('/workstation/commands')) {
      return new Response(JSON.stringify({ commands }))
    }
    return new Response(JSON.stringify({ token: 'a2', refresh_token: 'r2', expires_in: 3600 }))
  }) as unknown as typeof fetch
  return { f, calls }
}

test('a valid stop command kills the child and reports stop', async () => {
  const s = loadSession()!
  let killed = ''
  const c = cmd('stop')
  const { f } = stubFetch([{ command: c, signature: sign(c) }])
  const res = await pollCommands(s, pubB64, { kill: (sig) => ((killed = sig ?? ''), true) }, f)
  assert.equal(res.stop, true)
  assert.equal(killed, 'SIGTERM')
})

test('a command with a bad signature is ignored', async () => {
  const s = loadSession()!
  let killed = false
  const c = cmd('stop')
  const { f } = stubFetch([{ command: c, signature: 'AAAA' }])
  const res = await pollCommands(s, pubB64, { kill: () => ((killed = true), true) }, f)
  assert.equal(res.stop, false)
  assert.equal(killed, false)
})

test('a command signed by a different key is ignored', async () => {
  const s = loadSession()!
  const other = generateKeyPairSync('ed25519')
  const c = cmd('stop')
  const bad = nodeSign(null, Buffer.from(canonicalize(c)), other.privateKey).toString('base64')
  const { f } = stubFetch([{ command: c, signature: bad }])
  const res = await pollCommands(s, pubB64, { kill: () => true }, f)
  assert.equal(res.stop, false)
})

test('--no-verify (null key) ignores every command', async () => {
  const s = loadSession()!
  const c = cmd('stop')
  const { f } = stubFetch([{ command: c, signature: sign(c) }])
  const res = await pollCommands(s, null, { kill: () => true }, f)
  assert.equal(res.stop, false)
})

test('a valid refresh command hits the refresh endpoint', async () => {
  const s = loadSession()!
  const c = cmd('refresh')
  const { f, calls } = stubFetch([{ command: c, signature: sign(c) }])
  const res = await pollCommands(s, pubB64, { kill: () => true }, f)
  assert.equal(res.stop, false)
  assert.ok(calls.some((u) => u.endsWith('/persona-token/refresh')))
  assert.ok(calls.some((u) => u.includes('/commands/c1/ack')))
})
