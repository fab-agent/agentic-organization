import assert from 'node:assert/strict'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
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
const reqFiles = (dir: string) => files(dir).filter((f) => f.startsWith('activation.req.'))
const claimFiles = (dir: string) => files(dir).filter((f) => f.startsWith('activation.claim.'))
const liveFiles = (dir: string) => [...reqFiles(dir), ...claimFiles(dir)]
/** Make a claim look as if it was taken `ms` ago: its time lives in its name, so rename it. */
function makeStale(c: { path: string }, ms: number, now = NOW): void {
  const dir = c.path.slice(0, Math.max(c.path.lastIndexOf('/'), c.path.lastIndexOf('\\')))
  const name = c.path.slice(dir.length + 1)
  const aged = name.replace(/\.(\d{13})-([0-9a-f]{16})$/, (_m, _t, r) => `.${String(now - ms).padStart(13, '0')}-${r}`)
  renameSync(c.path, join(dir, aged)); c.path = join(dir, aged)
}
const ID16 = '0123456789abcdef'
const keyOf = (ts: number, id = ID16) => `${String(ts).padStart(13, '0')}-${id}`

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

test('the pending record is strict: its name and content must agree, and damaged, foreign, old or future records mean "nothing to do"', () => {
  const w = world()
  assert.equal(loadPending(w.stateDir, NOW), null)
  requestActivation(w.stateDir, 'finance-v2', NOW)
  const p = loadPending(w.stateDir, NOW)!
  assert.deepEqual({ ...p, id: '' }, { v: 1, id: '', layout: 'finance-v2', requested_at: NOW })
  assert.match(p.id, /^[0-9a-f]{16}$/)
  const [name] = reqFiles(w.stateDir); assert.equal(name, `activation.req.${keyOf(NOW, p.id)}`)
  // a hand-made record in a correctly named file
  const put = (ts: number, body: string, id = ID16) => { for (const f of reqFiles(w.stateDir)) rmSync(join(w.stateDir, f)); writeFileSync(join(w.stateDir, `activation.req.${keyOf(ts, id)}`), body) }
  const rec = (o: object) => JSON.stringify({ v: 1, id: ID16, layout: 'a', requested_at: NOW, ...o })
  put(NOW, rec({})); assert.ok(loadPending(w.stateDir, NOW), 'a well-formed one is accepted')
  for (const bad of ['', 'x', '[]', rec({ v: 2 }), rec({ layout: '../x' }), rec({ layout: 'A' }), rec({ id: 'f'.repeat(16) }), rec({ extra: 1 }),
    rec({ requested_at: `${NOW}` }), rec({ requested_at: NOW + 1 }), // the content disagrees with the name
    JSON.stringify({ v: 1, layout: 'a', requested_at: NOW }), rec({ layout: 'a'.repeat(5000) })]) {
    put(NOW, bad); assert.equal(loadPending(w.stateDir, NOW), null, bad.slice(0, 70))
  }
  put(NOW - PENDING_MAX_AGE_MS - 1, rec({ requested_at: NOW - PENDING_MAX_AGE_MS - 1 })); assert.equal(loadPending(w.stateDir, NOW), null, 'older than a week')
  put(NOW - PENDING_MAX_AGE_MS + 1000, rec({ requested_at: NOW - PENDING_MAX_AGE_MS + 1000 })); assert.ok(loadPending(w.stateDir, NOW), 'just inside a week')
  put(NOW + FUTURE_SKEW_MS + 1000, rec({ requested_at: NOW + FUTURE_SKEW_MS + 1000 })); assert.equal(loadPending(w.stateDir, NOW), null, 'too far in the future')
  put(NOW + FUTURE_SKEW_MS - 1000, rec({ requested_at: NOW + FUTURE_SKEW_MS - 1000 })); assert.ok(loadPending(w.stateDir, NOW), 'within the clock-skew allowance')
  // files that merely look similar are ignored
  for (const f of reqFiles(w.stateDir)) rmSync(join(w.stateDir, f))
  writeFileSync(join(w.stateDir, `activation.req.${keyOf(NOW)}.bak`), rec({})); writeFileSync(join(w.stateDir, 'activation.json'), rec({}))
  assert.equal(loadPending(w.stateDir, NOW), null)
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
  const real = join(w.root, 'real'); mkdirSync(real, { mode: 0o700 })
  for (const f of reqFiles(w.stateDir)) writeFileSync(join(real, f), readFileSync(join(w.stateDir, f)))
  const link = join(w.root, 'linked'); symlinkSync(real, link)
  assert.equal(loadPending(link, NOW), null)
  // a record that is too big is not read
  const [name] = reqFiles(w.stateDir); writeFileSync(join(w.stateDir, name!), ' '.repeat(5000)); assert.equal(loadPending(w.stateDir, NOW), null)
  // a record that is a link is not read
  rmSync(join(w.stateDir, name!)); symlinkSync(join(real, name!), join(w.stateDir, name!)); assert.equal(loadPending(w.stateDir, NOW), null)
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
  assert.equal(app.state.shown, 'finance-v2'); assert.deepEqual(liveFiles(w.stateDir), [])
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
  assert.deepEqual(liveFiles(w.stateDir), [])
})

test('ACT-1: a request written while another is being served is never removed by the first worker', async () => {
  for (const [first, second] of [['one', 'one'], ['one', 'two']] as const) {
    const w = world(); requestActivation(w.stateDir, first, NOW)
    const app = fakeApp(null) // no window yet: the worker waits, then gives up and tries to put its request back
    const v = virtual(); let wrote = false
    const sleep = async (ms: number) => { await v.sleep(ms); if (!wrote) { wrote = true; requestActivation(w.stateDir, second, NOW + 1) } }
    assert.equal(await activate(base(w, app.run, { waitSeconds: 3, clock: v.clock, sleep })), 'no_window')
    const p = loadPending(w.stateDir, NOW)!
    assert.equal(p.layout, second, 'the newer request is the one left')
    assert.equal(reqFiles(w.stateDir).length, 1, 'the older one did not come back'); assert.deepEqual(claimFiles(w.stateDir), [])
  }
})

test('ACT-1: a request that arrives after a window is found supersedes the one being served (no switch to the old one)', async () => {
  const w = world(); requestActivation(w.stateDir, 'old-layout', NOW)
  const app = fakeApp('main')
  const run: Runner = async (b, a, e, t) => { const r = await app.run(b, a, e, t); if (a[0] === 'status' && reqFiles(w.stateDir).length === 0 && claimFiles(w.stateDir).length === 1) requestActivation(w.stateDir, 'new-layout', NOW + 1); return r }
  assert.equal(await activate(base(w, run)), 'superseded')
  assert.equal(app.state.shown, 'main'); assert.equal(loadPending(w.stateDir, NOW)?.layout, 'new-layout')
  assert.equal(await activate(base(w, app.run)), 'switched'); assert.equal(app.state.shown, 'new-layout')
})

test('ACT-1: a claim left by a worker that died comes back after a while, and never comes back over a newer request', () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  const c = claim(w.stateDir, NOW)!
  assert.equal(c.pending.layout, 'finance-v2'); assert.equal(loadPending(w.stateDir, NOW), null) // held
  assert.equal(claim(w.stateDir, NOW), null)
  assert.equal(claim(w.stateDir, NOW + 4 * 60 * 1000), null) // 4 minutes: still held
  makeStale(c, STALE_CLAIM_MS + 1000) // the worker is gone
  const again = claim(w.stateDir, NOW)!
  assert.equal(again.pending.layout, 'finance-v2'); release(again, true)
  // with a newer request already there, a restored claim is dropped, not put over it
  requestActivation(w.stateDir, 'a', NOW + 2); const c2 = claim(w.stateDir, NOW)!
  requestActivation(w.stateDir, 'b', NOW + 3)
  release(c2, false)
  assert.equal(loadPending(w.stateDir, NOW)?.layout, 'b'); assert.equal(reqFiles(w.stateDir).length, 1); assert.deepEqual(claimFiles(w.stateDir), [])
})

test('no window: the request goes back; with a wait the app is polled once a second inside a real deadline', async () => {
  const w = world(); const app = fakeApp(null); requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.equal(await activate(base(w, app.run)), 'no_window')
  assert.equal(app.calls.length, 1); assert.equal(loadPending(w.stateDir, NOW)?.layout, 'finance-v2')
  // ACT-3: slow status calls (each uses ALL the time it is given, up to 10 s) cannot stretch the wait
  const vt = virtual(); const given: number[] = []
  const slowNo: Runner = async (_b, _a, _e, timeout) => { given.push(timeout); await vt.sleep(Math.min(timeout, 10_000)); return { code: 1, stdout: '' } }
  assert.equal(await activate(base(w, slowNo, { waitSeconds: 60, clock: vt.clock, sleep: vt.sleep })), 'no_window')
  assert.ok(vt.now <= 60_000, `took ${vt.now} ms of clock against a 60 s deadline`)
  assert.ok(given.every((g) => g >= 1 && g <= 10_000), JSON.stringify(given))
  assert.ok(given.length > 4 && given.length < 12, `${given.length} looks`) // not 61
  // a look never gets more than what is left, including the last sliver
  const vs = virtual(); const given2: number[] = []
  const quick: Runner = async (_b, _a, _e, timeout) => { given2.push(timeout); return { code: 1, stdout: '' } }
  await activate(base(w, quick, { waitSeconds: 2, clock: vs.clock, sleep: async (ms: number) => { await vs.sleep(ms) } }))
  assert.deepEqual(given2, [2000, 1000], 'the second look gets the remaining second, and nothing starts at the deadline')
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
  assert.deepEqual(liveFiles(w.stateDir), [])
})

test('a refused switch, or one the app does not show afterwards, keeps the request', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.equal(await activate(base(w, fakeApp('main', { switchFails: true }).run)), 'failed'); assert.ok(loadPending(w.stateDir, NOW))
  assert.equal(await activate(base(w, fakeApp('main', { ignoreSwitch: true }).run)), 'failed'); assert.ok(loadPending(w.stateDir, NOW))
  const g = fakeApp('main', { garbage: true })
  assert.equal(await activate(base(w, g.run)), 'failed')
  assert.ok(g.calls.some((c) => c.args[0] === 'do')); assert.ok(loadPending(w.stateDir, NOW))
  assert.equal(reqFiles(w.stateDir).length, 1); assert.deepEqual(claimFiles(w.stateDir), [], 'no claim file left')
})

test('the Herdr binary must be an absolute path to a real file, and a bad path does not consume the request', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW); const app = fakeApp('main')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: 'herdr' }), (e: ActivationError) => e.code === 'herdr_bin_not_absolute')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: join(w.root, 'missing') }), (e: ActivationError) => e.code === 'herdr_bin_missing')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: w.root }), (e: ActivationError) => e.code === 'herdr_bin_not_a_file')
  assert.equal(app.calls.length, 0, 'nothing was run'); assert.equal(reqFiles(w.stateDir).length, 1)
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


test('ACT-1: a request that was already taken and applied by another worker still supersedes the one a slow worker holds', async () => {
  for (const sameName of [false, true]) {
    const w = world(); requestActivation(w.stateDir, 'old-layout', NOW)
    const app = fakeApp('main')
    let release!: () => void; const hold = new Promise<void>((r) => { release = r })
    let first = true
    const slowFirst: Runner = async (b, a, e, t) => { if (first) { first = false; await hold } return app.run(b, a, e, t) }
    const oldWorker = activate(base(w, slowFirst)) // claimed the old request, stuck on its first status
    await new Promise((r) => setTimeout(r, 10))
    requestActivation(w.stateDir, sameName ? 'old-layout' : 'new-layout', NOW + 1)
    assert.equal(await activate(base(w, app.run)), 'switched') // the newer one is served completely
    const shownAfterNew = app.state.shown
    release()
    // consumed or not, it is no longer the newest. With the same name the window already shows it.
    assert.equal(await oldWorker, sameName ? 'already' : 'superseded')
    assert.equal(app.state.shown, shownAfterNew, 'the old worker did not switch back')
    assert.equal(app.calls.filter((c) => c.args[0] === 'do').length, 1)
  }
})

test('ACT-1: an old worker whose switch fails does not put its old request back over a newer, already-served one', async () => {
  const w = world(); requestActivation(w.stateDir, 'old-layout', NOW)
  const c = claim(w.stateDir, NOW)!
  requestActivation(w.stateDir, 'new-layout', NOW + 1)
  const served = claim(w.stateDir, NOW)!; release(served, true) // the newer one is done
  release(c, false) // the old one failed and is being given back
  assert.deepEqual(liveFiles(w.stateDir), [], 'nothing is left to serve; the old request did not come back')
  assert.equal(loadPending(w.stateDir, NOW), null)
})

test('ACT-5: writers need no coordination: whatever order two requests finish in, the later-made one is the one served', async () => {
  // B finishes writing before A although A carries the earlier time (it was slower to publish)
  const w = world()
  requestActivation(w.stateDir, 'layout-b', NOW + 10)
  requestActivation(w.stateDir, 'layout-a', NOW) // earlier time, published later: the clock rule lifts it above B
  const p = loadPending(w.stateDir, NOW)!
  assert.equal(p.layout, 'layout-a', 'the last one published is the newest: it never ends up behind an older one')
  assert.equal(p.requested_at, NOW, 'the record keeps the real time; only the ordering key is lifted')
  assert.ok(reqFiles(w.stateDir).some((f) => f.includes(String(NOW + 11).padStart(13, '0'))), 'the key is just above the older request')
  // same millisecond: two distinct files, a deterministic winner, one switch
  const w2 = world(); requestActivation(w2.stateDir, 'one', NOW); requestActivation(w2.stateDir, 'two', NOW)
  const app = fakeApp('main')
  assert.equal(await activate(base(w2, app.run)), 'switched'); assert.equal(app.state.shown, 'two')
  assert.equal(await activate(base(w2, app.run)), 'nothing')
  // files from an interrupted write (a stray temp name) never count
  const w3 = world(); requestActivation(w3.stateDir, 'x', NOW); writeFileSync(join(w3.stateDir, `activation.req.${keyOf(NOW + 5)}.tmp`), 'half')
  assert.equal(loadPending(w3.stateDir, NOW)?.layout, 'x')
})

test('markers stay (so "newer" can be seen later) but only the newest few', () => {
  const w = world()
  for (let i = 0; i < 30; i++) { requestActivation(w.stateDir, 'a', NOW + i); const c = claim(w.stateDir, NOW + i + 100)!; release(c, true) }
  assert.ok(files(w.stateDir).filter((f) => f.startsWith('activation.')).length <= 8)
  requestActivation(w.stateDir, 'z', NOW + 1000); assert.equal(loadPending(w.stateDir, NOW + 1000)?.layout, 'z')
})

test('ACT-4: a dead worker\'s claim is recovered by the ordinary entry point, not only by claim()', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  const dead = claim(w.stateDir, NOW)!
  const app = fakeApp('main')
  assert.equal(await activate(base(w, app.run)), 'nothing'); assert.equal(app.calls.length, 0) // not yet stale: held
  makeStale(dead, STALE_CLAIM_MS + 1000)
  assert.equal(await activate(base(w, app.run)), 'switched') // recovered and served in one go
  assert.equal(app.state.shown, 'finance-v2'); assert.deepEqual(liveFiles(w.stateDir), [])
  // with a newer request beside it, the recovered older one is dropped and the newer is served
  const w2 = world(); requestActivation(w2.stateDir, 'one', NOW); const dead2 = claim(w2.stateDir, NOW)!
  requestActivation(w2.stateDir, 'two', NOW + 1)
  makeStale(dead2, STALE_CLAIM_MS + 1000)
  const app2 = fakeApp('main')
  assert.equal(await activate(base(w2, app2.run)), 'switched'); assert.equal(app2.state.shown, 'two')
  // a claim that cannot be read back is simply removed
  const w3 = world(); requestActivation(w3.stateDir, 'x', NOW); const d3 = claim(w3.stateDir, NOW)!
  writeFileSync(d3.path, 'garbage'); makeStale(d3, STALE_CLAIM_MS + 1000)
  assert.equal(await activate(base(w3, fakeApp('main').run)), 'nothing'); assert.deepEqual(claimFiles(w3.stateDir), [])
})


test('ACT-6: two recoverers of one dead claim: the second, acting on an old observation, cannot take the first\'s new hold', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  const dead = claim(w.stateDir, NOW)!
  makeStale(dead, STALE_CLAIM_MS + 1000)
  const stale = readdirSync(w.stateDir).filter((f) => f.startsWith('activation.claim.')) // what recoverer B saw
  assert.equal(stale.length, 1)
  // A recovers it and takes it again (a fresh hold under a new name)
  const a = claim(w.stateDir, NOW)!
  assert.equal(a.pending.layout, 'finance-v2'); assert.notEqual(a.path, dead.path)
  // B now acts on its OLD observation: renaming that path fails, A's hold is untouched
  assert.throws(() => renameSync(join(w.stateDir, stale[0]!), join(w.stateDir, 'x')), /ENOENT/)
  assert.deepEqual(claimFiles(w.stateDir), [a.path.split(/[\\/]/).pop()])
  // and the original (dead) worker coming back cannot undo A's hold either
  release(dead, false)
  assert.deepEqual(claimFiles(w.stateDir), [a.path.split(/[\\/]/).pop()], 'the old holder touched nothing of the new one')
  release(a, true)
  assert.deepEqual(liveFiles(w.stateDir), [])
})

test('ACT-6: with the real entry points, two workers that both find the same stale claim serve it once', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  const dead = claim(w.stateDir, NOW)!
  makeStale(dead, STALE_CLAIM_MS + 1000)
  const app = fakeApp('main')
  const gate = new Promise<void>((r) => setTimeout(r, 20))
  const slow: Runner = async (b, a, e, t) => { await gate; return app.run(b, a, e, t) }
  const results = await Promise.all([activate(base(w, slow)), activate(base(w, slow)), activate(base(w, slow))])
  assert.deepEqual(results.slice().sort(), ['nothing', 'nothing', 'switched'])
  assert.equal(app.calls.filter((c) => c.args[0] === 'do').length, 1)
})

test('ACT-7: a clock that stepped back far beyond the skew does not make the new request unreadable', async () => {
  const w = world()
  for (let i = 0; i < 3; i++) { requestActivation(w.stateDir, 'a', NOW + i); const c = claim(w.stateDir, NOW + i)!; release(c, true) }
  // the clock now says 10 minutes EARLIER than the last request
  const back = NOW - 10 * 60 * 1000
  requestActivation(w.stateDir, 'after-rollback', back)
  const p = loadPending(w.stateDir, back)!
  assert.equal(p.layout, 'after-rollback'); assert.equal(p.requested_at, back, 'the record keeps the real time')
  const app = fakeApp('main')
  assert.equal(await activate(base(w, app.run, { now: () => back })), 'switched'); assert.equal(app.state.shown, 'after-rollback')
  // a small step back works the same
  requestActivation(w.stateDir, 'next', back - 1000); assert.equal(loadPending(w.stateDir, back - 1000)?.layout, 'next')
})


test('ACT-8: a claim\'s freshness is visible the instant the claim is, however old the request was', async () => {
  const w = world()
  // a request made 10 minutes ago and never served
  requestActivation(w.stateDir, 'finance-v2', NOW - 10 * 60 * 1000)
  const a = claim(w.stateDir, NOW)!
  // another worker observing the claim right now (before anything else happens to the file) sees it as just taken
  const seen = readdirSync(w.stateDir).filter((f) => f.startsWith('activation.claim.'))
  const taken = Number(/\.(\d{13})-[0-9a-f]{16}$/.exec(seen[0]!)![1])
  assert.equal(taken, NOW, 'the time of taking is in the name, not the request\'s old mtime')
  const app = fakeApp('main')
  assert.equal(await activate(base(w, app.run)), 'nothing'); assert.equal(app.calls.length, 0) // not stale: left alone
  assert.deepEqual(claimFiles(w.stateDir), seen)
  release(a, true)
})
