import assert from 'node:assert/strict'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  ActivationError, FUTURE_SKEW_MS, PENDING_MAX_AGE_MS, STALE_CLAIM_MS, activate, claim, loadPending, release, requestActivation, type Ran, type Runner,
} from '../src/utils/activation.js'

const NOW = Date.now()
const POSIX = process.platform !== 'win32'

function world() {
  const root = mkdtempSync(join(tmpdir(), 'act-'))
  const stateDir = join(root, 'state'), appHome = join(root, 'app')
  mkdirSync(appHome, { recursive: true })
  const herdrBin = join(root, POSIX ? 'herdr' : 'herdr.exe')
  writeFileSync(herdrBin, '#!/bin/sh\n'); if (POSIX) chmodSync(herdrBin, 0o755)
  return { root, stateDir, appHome, herdrBin }
}
const files = (dir: string) => readdirSync(dir).sort()
const activationFiles = (dir: string) => files(dir).filter((f) => f.startsWith('activation'))

/** A fake window: `shown` is the layout it shows (null: no window), `do layout.switch` changes it. */
function fakeApp(shown: string | null, opts: { switchFails?: boolean; ignoreSwitch?: boolean; garbage?: boolean } = {}) {
  const calls: { args: string[]; env: NodeJS.ProcessEnv }[] = []
  const state = { shown }
  const run: Runner = async (_bin, args, env): Promise<Ran> => {
    calls.push({ args, env })
    if (state.shown === null) return { code: 1, stdout: '' } // "no Herdr window at ..."
    if (args[0] === 'status') return { code: 0, stdout: opts.garbage ? 'not json' : JSON.stringify({ layout: state.shown, errors: [] }) }
    if (args[0] === 'do' && args[1] === 'layout.switch') {
      if (opts.switchFails) return { code: 1, stdout: '' }
      if (!opts.ignoreSwitch) state.shown = args[args.indexOf('--name') + 1]!
      return { code: 0, stdout: '{}' }
    }
    return { code: 2, stdout: '' }
  }
  return { run, calls, state }
}
/** Virtual time: sleeping advances the monotonic clock, so a deadline is reached without waiting. */
function virtual() {
  let t = 0
  return { clock: () => t, sleep: async (ms: number) => { t += ms }, get now() { return t } }
}
const base = (w: ReturnType<typeof world>, run: Runner, extra = {}) => ({ stateDir: w.stateDir, appHome: w.appHome, herdrBin: w.herdrBin, runner: run, now: () => NOW, ...extra })

test('the pending record is strict: damaged, foreign, old or future records mean "nothing to do"', () => {
  const w = world()
  assert.equal(loadPending(w.stateDir, NOW), null)
  requestActivation(w.stateDir, 'finance-v2', NOW)
  const p = loadPending(w.stateDir, NOW)!
  assert.deepEqual({ ...p, id: '' }, { v: 1, id: '', layout: 'finance-v2', requested_at: NOW })
  assert.match(p.id, /^[0-9a-f]{16}$/)
  const file = join(w.stateDir, 'activation.json')
  const id = '0123456789abcdef'
  const put = (s: string) => writeFileSync(file, s)
  const rec = (o: object) => JSON.stringify({ v: 1, id, layout: 'a', requested_at: NOW, ...o })
  for (const bad of ['', 'x', '[]', rec({ v: 2 }), rec({ layout: '../x' }), rec({ layout: 'A' }), rec({ id: 'short' }), rec({ id: 'G'.repeat(16) }), rec({ extra: 1 }),
    rec({ requested_at: `${NOW}` }), rec({ requested_at: -1 }), rec({ requested_at: NOW - PENDING_MAX_AGE_MS - 1 }), rec({ requested_at: NOW + FUTURE_SKEW_MS + 1000 }),
    JSON.stringify({ v: 1, layout: 'a', requested_at: NOW }), // no id
    rec({ layout: 'a'.repeat(5000) })]) {
    put(bad); assert.equal(loadPending(w.stateDir, NOW), null, bad.slice(0, 70))
  }
  put(rec({ requested_at: NOW - PENDING_MAX_AGE_MS + 1000 })); assert.ok(loadPending(w.stateDir, NOW), 'just inside a week')
  put(rec({ requested_at: NOW + FUTURE_SKEW_MS - 1000 })); assert.ok(loadPending(w.stateDir, NOW), 'within the clock-skew allowance')
})

test('a request for a name that is not a layout name is refused', () => {
  const w = world()
  for (const bad of ['', '../x', 'A', 'a b', 'a/b', 'x'.repeat(65)]) assert.throws(() => requestActivation(w.stateDir, bad, NOW), (e: ActivationError) => e.code === 'bad_layout')
})

test('ACT-2: a state folder that is not the caller\'s private one is not trusted, even with a well-formed record', { skip: !POSIX }, async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  chmodSync(w.stateDir, 0o777) // shared with other users
  assert.equal(loadPending(w.stateDir, NOW), null)
  const app = fakeApp('main')
  assert.equal(await activate(base(w, app.run)), 'nothing'); assert.equal(app.calls.length, 0, 'the app was not even asked')
  chmodSync(w.stateDir, 0o700)
  // a link where the folder should be
  const real = join(w.root, 'real'); mkdirSync(real, { mode: 0o700 }); writeFileSync(join(real, 'activation.json'), readFileSync(join(w.stateDir, 'activation.json')))
  const link = join(w.root, 'linked'); symlinkSync(real, link)
  assert.equal(loadPending(link, NOW), null)
  // a record that is a link, or too big, is not read
  const big = join(w.stateDir, 'activation.json'); writeFileSync(big, ' '.repeat(5000)); assert.equal(loadPending(w.stateDir, NOW), null)
})

test('nothing pending: the app is not even asked', async () => {
  const w = world(); const app = fakeApp('main')
  assert.equal(await activate(base(w, app.run)), 'nothing')
  assert.equal(app.calls.length, 0)
})

test('a window showing another layout is switched, verified, and the request consumed; exact argv and app home', async () => {
  const w = world(); const app = fakeApp('main'); requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.equal(await activate(base(w, app.run)), 'switched')
  assert.deepEqual(app.calls.map((c) => c.args), [['status'], ['do', 'layout.switch', '--name', 'finance-v2'], ['status']])
  assert.ok(app.calls.every((c) => c.env.HERDR_APP_HOME === w.appHome))
  assert.equal(app.state.shown, 'finance-v2'); assert.deepEqual(activationFiles(w.stateDir), [])
  assert.equal(await activate(base(w, app.run)), 'nothing') // honoured once: not done again
})

test('already showing it: no switch, request consumed. A person who moved elsewhere afterwards is not fought', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  const app = fakeApp('finance-v2')
  assert.equal(await activate(base(w, app.run)), 'already')
  assert.deepEqual(app.calls.map((c) => c.args), [['status']])
  app.state.shown = 'win98'
  assert.equal(await activate(base(w, app.run)), 'nothing'); assert.equal(app.state.shown, 'win98')
})

test('ACT-1: two workers, one request: exactly one claims it and exactly one switch is sent', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  const app = fakeApp('main')
  const gate = new Promise<void>((r) => setTimeout(r, 20))
  const slow: Runner = async (b, a, e, t) => { await gate; return app.run(b, a, e, t) }
  const results = await Promise.all([activate(base(w, slow)), activate(base(w, slow)), activate(base(w, slow))])
  assert.deepEqual(results.slice().sort(), ['nothing', 'nothing', 'switched'])
  assert.equal(app.calls.filter((c) => c.args[0] === 'do').length, 1)
  assert.deepEqual(activationFiles(w.stateDir), [])
})

test('ACT-1: a request written while another is being served is never removed by the first worker', async () => {
  for (const [first, second] of [['one', 'one'], ['one', 'two']] as const) {
    const w = world(); requestActivation(w.stateDir, first, NOW)
    const app = fakeApp(null) // no window yet: the worker waits, then gives up and puts its request back
    const v = virtual()
    const sleep = async (ms: number) => { await v.sleep(ms); if (!existsSync(join(w.stateDir, 'activation.json'))) requestActivation(w.stateDir, second, NOW + 1) }
    assert.equal(await activate(base(w, app.run, { waitSeconds: 3, clock: v.clock, sleep })), 'no_window')
    const p = loadPending(w.stateDir, NOW)!
    assert.equal(p.layout, second, 'the newer request is the one left')
    assert.deepEqual(activationFiles(w.stateDir), ['activation.json'], 'no claim file is left behind')
  }
})

test('ACT-1: a request that arrives after a window is found supersedes the one being served (no switch to the old one)', async () => {
  const w = world(); requestActivation(w.stateDir, 'old-layout', NOW)
  const app = fakeApp('main')
  const run: Runner = async (b, a, e, t) => { const r = await app.run(b, a, e, t); if (a[0] === 'status' && !existsSync(join(w.stateDir, 'activation.json'))) requestActivation(w.stateDir, 'new-layout', NOW + 1); return r }
  assert.equal(await activate(base(w, run)), 'superseded')
  assert.equal(app.state.shown, 'main'); assert.equal(loadPending(w.stateDir, NOW)?.layout, 'new-layout')
  assert.equal(await activate(base(w, app.run)), 'switched'); assert.equal(app.state.shown, 'new-layout')
})

test('ACT-1: a claim left by a worker that died comes back after a while, and never overwrites a newer request', () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  const c = claim(w.stateDir, NOW)!
  assert.equal(c.pending.layout, 'finance-v2'); assert.equal(loadPending(w.stateDir, NOW), null) // held
  assert.equal(claim(w.stateDir, NOW), null)
  // 4 minutes: still held. 6 minutes (the worker is gone): restored for the next one.
  assert.equal(claim(w.stateDir, NOW + 4 * 60 * 1000), null)
  const old = new Date(NOW - STALE_CLAIM_MS - 1000); utimesSync(c.path, old, old)
  const again = claim(w.stateDir, NOW)!
  assert.equal(again.pending.layout, 'finance-v2'); release(again, true)
  // with a newer request already there, a restored claim is dropped, not put over it
  requestActivation(w.stateDir, 'a', NOW); const c2 = claim(w.stateDir, NOW)!
  requestActivation(w.stateDir, 'b', NOW + 1)
  release(c2, false)
  assert.equal(loadPending(w.stateDir, NOW)?.layout, 'b'); assert.deepEqual(activationFiles(w.stateDir), ['activation.json'])
})

test('no window: the request goes back; with a wait the app is polled once a second inside a real deadline', async () => {
  const w = world(); const app = fakeApp(null); requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.equal(await activate(base(w, app.run)), 'no_window')
  assert.equal(app.calls.length, 1); assert.equal(loadPending(w.stateDir, NOW)?.layout, 'finance-v2')
  // slow status calls (each takes 10 s of the clock) consume the deadline: ACT-3, not 61 x 10 s
  let t = 0; const sleeps: number[] = []
  const slowNo: Runner = async () => { t += 10_000; return { code: 1, stdout: '' } }
  assert.equal(await activate(base(w, slowNo, { waitSeconds: 60, clock: () => t, sleep: async (ms: number) => { sleeps.push(ms); t += ms } })), 'no_window')
  assert.ok(t <= 60_000 + 10_000 + 1000, `took ${t} ms of clock`)
  // the window opens during the wait
  const app3 = fakeApp(null); let n = 0
  const opening: Runner = (b, a, e, tt) => { if (++n === 3) app3.state.shown = 'main'; return app3.run(b, a, e, tt) }
  const v3 = virtual()
  assert.equal(await activate(base(w, opening, { waitSeconds: 10, clock: v3.clock, sleep: v3.sleep })), 'switched')
  // the wait is capped
  const v4 = virtual(); requestActivation(w.stateDir, 'x', NOW)
  await activate(base(w, fakeApp(null).run, { waitSeconds: 99999, clock: v4.clock, sleep: v4.sleep }))
  assert.ok(v4.now <= 121_000, `waited ${v4.now} ms`)
})

test('ACT-3: a record that expires while waiting is not served', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW - PENDING_MAX_AGE_MS + 2000)
  let wall = NOW; const app = fakeApp(null); const app2 = fakeApp('main')
  let calls = 0
  const run: Runner = (b, a, e, t) => { calls++; if (calls === 3) { wall = NOW + 5000; return app2.run(b, a, e, t) } return app.run(b, a, e, t) }
  const v5 = virtual()
  const out = await activate({ stateDir: w.stateDir, appHome: w.appHome, herdrBin: w.herdrBin, runner: run, now: () => wall, waitSeconds: 10, clock: v5.clock, sleep: v5.sleep })
  assert.equal(out, 'nothing'); assert.equal(app2.calls.filter((c) => c.args[0] === 'do').length, 0)
  assert.deepEqual(activationFiles(w.stateDir), [])
})

test('a refused switch, or one the app does not show afterwards, keeps the request', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.equal(await activate(base(w, fakeApp('main', { switchFails: true }).run)), 'failed'); assert.ok(loadPending(w.stateDir, NOW))
  assert.equal(await activate(base(w, fakeApp('main', { ignoreSwitch: true }).run)), 'failed'); assert.ok(loadPending(w.stateDir, NOW))
  const g = fakeApp('main', { garbage: true })
  assert.equal(await activate(base(w, g.run)), 'failed')
  assert.ok(g.calls.some((c) => c.args[0] === 'do')); assert.ok(loadPending(w.stateDir, NOW))
  assert.deepEqual(activationFiles(w.stateDir), ['activation.json'], 'no claim file left')
})

test('the Herdr binary must be an absolute path to a real file, and a bad path does not consume the request', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW); const app = fakeApp('main')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: 'herdr' }), (e: ActivationError) => e.code === 'herdr_bin_not_absolute')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: join(w.root, 'missing') }), (e: ActivationError) => e.code === 'herdr_bin_missing')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: w.root }), (e: ActivationError) => e.code === 'herdr_bin_not_a_file')
  assert.equal(app.calls.length, 0, 'nothing was run'); assert.deepEqual(activationFiles(w.stateDir), ['activation.json'])
  if (POSIX) {
    const link = join(w.root, 'link'); symlinkSync(w.herdrBin, link)
    await assert.rejects(activate({ ...base(w, app.run), herdrBin: link }), (e: ActivationError) => e.code === 'herdr_bin_not_a_file')
  }
})

test('with the real process runner: a stand-in app script is run by argv, with the app home in its environment', { skip: !POSIX }, async () => {
  const w = world()
  const log = join(w.root, 'calls.log'), shown = join(w.root, 'shown.txt')
  writeFileSync(shown, 'main')
  writeFileSync(w.herdrBin, `#!/bin/sh
echo "$HERDR_APP_HOME|$*" >> '${log}'
case "$1" in
  status) printf '{"layout":"%s","errors":[]}' "$(cat '${shown}')" ;;
  do) [ "$2" = layout.switch ] && [ "$3" = --name ] && printf '%s' "$4" > '${shown}' ;;
  *) exit 2 ;;
esac
`)
  chmodSync(w.herdrBin, 0o755)
  requestActivation(w.stateDir, 'finance-v2')
  assert.equal(await activate({ stateDir: w.stateDir, appHome: w.appHome, herdrBin: w.herdrBin }), 'switched')
  assert.deepEqual(readFileSync(log, 'utf8').trim().split('\n'), [`${w.appHome}|status`, `${w.appHome}|do layout.switch --name finance-v2`, `${w.appHome}|status`])
  assert.equal(readFileSync(shown, 'utf8'), 'finance-v2')
  writeFileSync(w.herdrBin, '#!/bin/sh\necho "no Herdr window" >&2\nexit 1\n'); chmodSync(w.herdrBin, 0o755)
  requestActivation(w.stateDir, 'finance-v3')
  assert.equal(await activate({ stateDir: w.stateDir, appHome: w.appHome, herdrBin: w.herdrBin }), 'no_window')
  assert.equal(loadPending(w.stateDir)?.layout, 'finance-v3')
})
