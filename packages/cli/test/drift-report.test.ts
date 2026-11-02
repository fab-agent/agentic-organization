import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { ReportError, buildReport, sendReport } from '../src/utils/drift-report.js'
import { freshState, saveState } from '../src/utils/workspace-state.js'

const H = 'a'.repeat(64)

function world(installed = true) {
  const root = mkdtempSync(join(tmpdir(), 'drift-'))
  const stateDir = join(root, 'state'), appHome = join(root, 'app')
  mkdirSync(appHome, { recursive: true })
  if (installed) saveState(stateDir, { ...freshState(), installed: { generation: 5, epoch: 2, content_digest: H } })
  return { root, stateDir, appHome }
}
const managed = (appHome: string, m: unknown) => writeFileSync(join(appHome, '.3pa-managed.json'), JSON.stringify(m))

test('the report is counts and the installed record, nothing that names a file', () => {
  const w = world()
  managed(w.appHome, {
    v: 1,
    layout: { name: 'secret-layout-name', sha256: H },
    mods: { 'finance-private-mod': { version: '1.0.0', files: { 'main.js': H, 'extra/x.js': H } } },
  })
  mkdirSync(join(w.appHome, 'mods', 'stranger'), { recursive: true }) // an unmanaged mod
  const r = buildReport(w.appHome, w.stateDir, '1.4.2')!
  assert.deepEqual(r, { client_version: '1.4.2', epoch: 2, generation: 5, missing: 2, modified: 0, extra: 0, unmanaged: 1, interrupted: false })
  const text = JSON.stringify(r)
  for (const leak of ['secret-layout-name', 'finance-private-mod', 'stranger', 'main.js', w.appHome, w.root]) assert.ok(!text.includes(leak), leak)
  assert.deepEqual(Object.keys(r).sort(), ['client_version', 'epoch', 'extra', 'generation', 'interrupted', 'missing', 'modified', 'unmanaged'])
})

test('a journal waiting to be rolled back is reported as interrupted; a bad version is not echoed', () => {
  const w = world()
  writeFileSync(join(w.appHome, '.3pa-journal.json'), '{}')
  const r = buildReport(w.appHome, w.stateDir, 'v1; <script>')!
  assert.equal(r.interrupted, true)
  assert.equal(r.client_version, 'unknown')
})

test('nothing installed: nothing to report, and nothing is sent', async () => {
  const w = world(false)
  assert.equal(buildReport(w.appHome, w.stateDir, '1.0.0'), null)
  let calls = 0
  const fetchImpl = (async () => { calls++; return new Response(null, { status: 204 }) }) as typeof fetch
  assert.equal(await sendReport({ baseUrl: 'https://p.example', webToken: 't', appHome: w.appHome, stateDir: w.stateDir, clientVersion: '1.0.0', fetchImpl }), 'nothing_installed')
  assert.equal(calls, 0)
})

function sender(status: number | Error) {
  const seen: { url: string; init?: RequestInit }[] = []
  const fetchImpl = (async (u: string | URL | Request, init?: RequestInit) => {
    seen.push({ url: String(u), init })
    if (status instanceof Error) throw status
    return new Response(null, { status })
  }) as typeof fetch
  return { seen, fetchImpl }
}
const base = (w: ReturnType<typeof world>, extra = {}) => ({ baseUrl: 'https://p.example/', webToken: 'tok', appHome: w.appHome, stateDir: w.stateDir, clientVersion: '1.0.0', ...extra })

test('send: POST with the session token, no redirects, the company only as a query', async () => {
  const w = world(); const s = sender(204)
  assert.equal(await sendReport({ ...base(w, { companyId: 'c 1&x' }), fetchImpl: s.fetchImpl }), 'sent')
  const { url, init } = s.seen[0]!
  assert.equal(url, 'https://p.example/me/workspace/report?company_id=c%201%26x')
  assert.equal(init?.method, 'POST'); assert.equal(init?.redirect, 'error')
  assert.equal((init?.headers as Record<string, string>).Authorization, 'Bearer tok')
  const body = JSON.parse(String(init?.body)); assert.equal(body.generation, 5); assert.equal(body.person_id, undefined)
})

test('send: too soon is not an error; other statuses and network failures are stable codes', async () => {
  const w = world()
  assert.equal(await sendReport({ ...base(w), fetchImpl: sender(429).fetchImpl }), 'too_soon')
  for (const [status, code] of [[401, 'http_401'], [422, 'http_422'], [500, 'http_500']] as const) {
    await assert.rejects(sendReport({ ...base(w), fetchImpl: sender(status).fetchImpl }), (e: ReportError) => e.code === code)
  }
  await assert.rejects(sendReport({ ...base(w), fetchImpl: sender(new TypeError('connect ECONNREFUSED 10.0.0.1')).fetchImpl }), (e: ReportError) => e.code === 'report_failed' && !e.message.includes('10.0.0.1'))
  const timeout = Object.assign(new Error('x'), { name: 'TimeoutError' })
  await assert.rejects(sendReport({ ...base(w), fetchImpl: sender(timeout).fetchImpl }), (e: ReportError) => e.code === 'report_timeout')
})

test('send: the token is never sent to a non-https, non-loopback platform URL', async () => {
  const w = world(); const s = sender(204)
  await assert.rejects(sendReport({ ...base(w, { baseUrl: 'http://platform.example' }), fetchImpl: s.fetchImpl }))
  assert.equal(s.seen.length, 0)
})
