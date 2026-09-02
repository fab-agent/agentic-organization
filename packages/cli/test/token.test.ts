import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

// token.ts / login.ts write a session file — keep it out of the real ~/.config.
process.env.THREEPA_SESSION_FILE = join(
  mkdtempSync(join(tmpdir(), '3pa-test-')),
  'session.json',
)

import type { Session } from '../src/commands/login.ts'
import { ensureFreshToken, isExpiring, refreshNow } from '../src/utils/token.ts'

const base: Session = {
  base_url: 'https://x',
  token: 'old-access',
  refresh_token: 'old-refresh',
  persona_id: 'p1',
  persona_name: 'Ada',
  saved_at: new Date().toISOString(),
}

test('isExpiring: false with no expiry, true inside the skew window', () => {
  assert.equal(isExpiring(base), false)
  assert.equal(
    isExpiring({ ...base, token_expires_at: new Date(Date.now() + 3_600_000).toISOString() }),
    false,
  )
  assert.equal(
    isExpiring({ ...base, token_expires_at: new Date(Date.now() + 30_000).toISOString() }),
    true,
  )
})

test('refreshNow posts the refresh token and returns the rotated pair', async () => {
  let seen: any = null
  const stub = (async (url: string, init: RequestInit) => {
    seen = { url, body: JSON.parse(init.body as string) }
    return new Response(
      JSON.stringify({ token: 'new-access', refresh_token: 'new-refresh', expires_in: 3600 }),
    )
  }) as unknown as typeof fetch

  const out = await refreshNow(base, stub)
  assert.equal(seen.url, 'https://x/workstation/persona-token/refresh')
  assert.equal(seen.body.refresh_token, 'old-refresh')
  assert.equal(out.token, 'new-access')
  assert.equal(out.refresh_token, 'new-refresh')
  assert.ok(out.token_expires_at && Date.parse(out.token_expires_at) > Date.now())
})

test('refreshNow throws on a non-2xx', async () => {
  const stub = (async () => new Response('nope', { status: 401 })) as typeof fetch
  await assert.rejects(refreshNow(base, stub), /refresh failed \(401\)/)
})

test('refreshNow throws without a refresh token', async () => {
  await assert.rejects(refreshNow({ ...base, refresh_token: undefined }), /no refresh token/)
})

test('ensureFreshToken is a no-op when not expiring', async () => {
  let called = false
  const stub = (async () => {
    called = true
    return new Response('{}')
  }) as typeof fetch
  const out = await ensureFreshToken(base, stub)
  assert.equal(called, false)
  assert.equal(out, base)
})

test('ensureFreshToken refreshes when expiring, and swallows failures', async () => {
  const expiring = { ...base, token_expires_at: new Date(Date.now() + 10_000).toISOString() }

  const okStub = (async () =>
    new Response(
      JSON.stringify({ token: 'a2', refresh_token: 'r2', expires_in: 3600 }),
    )) as typeof fetch
  assert.equal((await ensureFreshToken(expiring, okStub)).token, 'a2')

  const failStub = (async () => new Response('x', { status: 500 })) as typeof fetch
  assert.equal((await ensureFreshToken(expiring, failStub)).token, 'old-access')
})
