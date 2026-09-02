import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

const dir = mkdtempSync(join(tmpdir(), '3pa-ops-'))
process.env.THREEPA_SESSION_FILE = join(dir, 'session.json')
writeFileSync(
  process.env.THREEPA_SESSION_FILE,
  JSON.stringify({
    base_url: 'https://x',
    token: 't',
    persona_id: 'p1',
    persona_name: 'Ada',
    saved_at: new Date().toISOString(),
  }),
)

const { api, requireSession } = await import('../src/utils/backend.ts')

test('requireSession loads the session file', async () => {
  const s = await requireSession()
  assert.equal(s.persona_id, 'p1')
})

test('api() attaches the bearer token and parses JSON', async () => {
  let seen: any = null
  const stub = (async (url: string, init: RequestInit) => {
    seen = { url, auth: (init.headers as any).Authorization }
    return new Response(JSON.stringify({ mode: 'dry_run', rules: [] }))
  }) as unknown as typeof fetch
  // @ts-expect-error swap global fetch for the test
  globalThis.fetch = stub
  const s = await requireSession()
  const body = await api(s, '/workstation/policy')
  assert.equal(seen.url, 'https://x/workstation/policy')
  assert.equal(seen.auth, 'Bearer t')
  assert.deepEqual(body, { mode: 'dry_run', rules: [] })
})

test('api() throws the backend detail on a non-2xx', async () => {
  const stub = (async () =>
    new Response(JSON.stringify({ detail: 'nope' }), { status: 403 })) as typeof fetch
  // @ts-expect-error test swap
  globalThis.fetch = stub
  const s = await requireSession()
  await assert.rejects(api(s, '/x'), /nope/)
})
