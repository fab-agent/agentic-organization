import assert from 'node:assert/strict'
import { chmodSync, mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  ActivationError, PENDING_MAX_AGE_MS, activate, clearPending, loadPending, requestActivation, type Ran, type Runner,
} from '../src/utils/activation.js'

const NOW = 1_800_000_000_000

function world() {
  const root = mkdtempSync(join(tmpdir(), 'act-'))
  const stateDir = join(root, 'state'), appHome = join(root, 'app')
  mkdirSync(appHome, { recursive: true })
  const herdrBin = join(root, process.platform === 'win32' ? 'herdr.exe' : 'herdr')
  writeFileSync(herdrBin, '#!/bin/sh\n'); if (process.platform !== 'win32') chmodSync(herdrBin, 0o755)
  return { root, stateDir, appHome, herdrBin }
}

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
const base = (w: ReturnType<typeof world>, run: Runner, extra = {}) => ({ stateDir: w.stateDir, appHome: w.appHome, herdrBin: w.herdrBin, runner: run, now: () => NOW, ...extra })

test('the pending record is strict: damaged, foreign, old or future records mean "nothing to do"', () => {
  const w = world()
  assert.equal(loadPending(w.stateDir, NOW), null)
  requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.deepEqual(loadPending(w.stateDir, NOW), { v: 1, layout: 'finance-v2', requested_at: NOW })
  const file = join(w.stateDir, 'activation.json')
  const put = (s: string) => writeFileSync(file, s)
  for (const bad of ['', 'x', '[]', '{"v":2,"layout":"a","requested_at":1}', '{"v":1,"layout":"../x","requested_at":1}', '{"v":1,"layout":"A","requested_at":1}',
    `{"v":1,"layout":"a","requested_at":${NOW},"extra":1}`, `{"v":1,"layout":"a","requested_at":"${NOW}"}`, `{"v":1,"layout":"a","requested_at":-1}`,
    `{"v":1,"layout":"a","requested_at":${NOW - PENDING_MAX_AGE_MS - 1}}`, `{"v":1,"layout":"a","requested_at":${NOW + 10 * 60 * 1000}}`,
    '{"v":1,"layout":"' + 'a'.repeat(5000) + '","requested_at":1}']) {
    put(bad); assert.equal(loadPending(w.stateDir, NOW), null, bad.slice(0, 60))
  }
  put(`{"v":1,"layout":"a","requested_at":${NOW - PENDING_MAX_AGE_MS + 1000}}`)
  assert.ok(loadPending(w.stateDir, NOW), 'just inside a week')
})

test('a request for a name that is not a layout name is refused; clearing keeps a newer request', () => {
  const w = world()
  for (const bad of ['', '../x', 'A', 'a b', 'a/b', 'x'.repeat(65)]) assert.throws(() => requestActivation(w.stateDir, bad, NOW), (e: ActivationError) => e.code === 'bad_layout')
  requestActivation(w.stateDir, 'one', NOW)
  clearPending(w.stateDir, 'two', NOW) // an older run clearing something it did not ask for
  assert.equal(loadPending(w.stateDir, NOW)?.layout, 'one')
  clearPending(w.stateDir, 'one', NOW)
  assert.equal(loadPending(w.stateDir, NOW), null)
})

test('nothing pending: the app is not even asked', async () => {
  const w = world(); const app = fakeApp('main')
  assert.equal(await activate(base(w, app.run)), 'nothing')
  assert.equal(app.calls.length, 0)
})

test('a window showing another layout is switched, verified, and the request cleared; exact argv and app home', async () => {
  const w = world(); const app = fakeApp('main'); requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.equal(await activate(base(w, app.run)), 'switched')
  assert.deepEqual(app.calls.map((c) => c.args), [['status'], ['do', 'layout.switch', '--name', 'finance-v2'], ['status']])
  assert.ok(app.calls.every((c) => c.env.HERDR_APP_HOME === w.appHome))
  assert.equal(app.state.shown, 'finance-v2'); assert.equal(loadPending(w.stateDir, NOW), null)
  assert.equal(await activate(base(w, app.run)), 'nothing') // honoured once: not done again
})

test('already showing it: no switch, request cleared. A person who moved elsewhere afterwards is not fought', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  const app = fakeApp('finance-v2')
  assert.equal(await activate(base(w, app.run)), 'already')
  assert.deepEqual(app.calls.map((c) => c.args), [['status']])
  app.state.shown = 'win98' // the person switches on purpose
  assert.equal(await activate(base(w, app.run)), 'nothing'); assert.equal(app.state.shown, 'win98')
})

test('no window: the request stays; with a wait the app is polled once a second, then given up on quietly', async () => {
  const w = world(); const app = fakeApp(null); requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.equal(await activate(base(w, app.run)), 'no_window')
  assert.equal(app.calls.length, 1); assert.ok(loadPending(w.stateDir, NOW))
  const sleeps: number[] = []; const app2 = fakeApp(null)
  assert.equal(await activate(base(w, app2.run, { waitSeconds: 3, sleep: async (ms: number) => { sleeps.push(ms) } })), 'no_window')
  assert.deepEqual(sleeps, [1000, 1000, 1000]); assert.equal(app2.calls.length, 4); assert.ok(loadPending(w.stateDir, NOW))
  // the window opens during the wait
  const app3 = fakeApp(null); let n = 0
  const opening: Runner = (b, a, e, t) => { if (++n === 3) app3.state.shown = 'main'; return app3.run(b, a, e, t) }
  assert.equal(await activate(base(w, opening, { waitSeconds: 10, sleep: async () => {} })), 'switched')
  // the wait is capped
  const cap: number[] = []
  await activate(base(w, fakeApp(null).run, { waitSeconds: 99999, sleep: async (ms: number) => { cap.push(ms) } }))
  assert.ok(cap.length <= 120)
})

test('a refused switch, or one the app does not show afterwards, keeps the request', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW)
  assert.equal(await activate(base(w, fakeApp('main', { switchFails: true }).run)), 'failed'); assert.ok(loadPending(w.stateDir, NOW))
  assert.equal(await activate(base(w, fakeApp('main', { ignoreSwitch: true }).run)), 'failed'); assert.ok(loadPending(w.stateDir, NOW))
  // an unreadable status answer is "unknown", never "already": the switch is attempted
  const g = fakeApp('main', { garbage: true })
  assert.equal(await activate(base(w, g.run)), 'failed')
  assert.ok(g.calls.some((c) => c.args[0] === 'do'))
})

test('the Herdr binary must be an absolute path to a real file', async () => {
  const w = world(); requestActivation(w.stateDir, 'finance-v2', NOW); const app = fakeApp('main')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: 'herdr' }), (e: ActivationError) => e.code === 'herdr_bin_not_absolute')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: join(w.root, 'missing') }), (e: ActivationError) => e.code === 'herdr_bin_missing')
  await assert.rejects(activate({ ...base(w, app.run), herdrBin: w.root }), (e: ActivationError) => e.code === 'herdr_bin_not_a_file')
  assert.equal(app.calls.length, 0, 'nothing was run')
  if (process.platform !== 'win32') {
    const link = join(w.root, 'link'); symlinkSync(w.herdrBin, link)
    await assert.rejects(activate({ ...base(w, app.run), herdrBin: link }), (e: ActivationError) => e.code === 'herdr_bin_not_a_file')
  }
})

test('with the real process runner: a stand-in app script is run by argv, with the app home in its environment', { skip: process.platform === 'win32' }, async () => {
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
  const lines = (await import('node:fs')).readFileSync(log, 'utf8').trim().split('\n')
  assert.deepEqual(lines, [`${w.appHome}|status`, `${w.appHome}|do layout.switch --name finance-v2`, `${w.appHome}|status`])
  assert.equal((await import('node:fs')).readFileSync(shown, 'utf8'), 'finance-v2')
  // an app that is not open answers with a failure: the request waits
  writeFileSync(w.herdrBin, '#!/bin/sh\necho "no Herdr window" >&2\nexit 1\n'); chmodSync(w.herdrBin, 0o755)
  requestActivation(w.stateDir, 'finance-v3')
  assert.equal(await activate({ stateDir: w.stateDir, appHome: w.appHome, herdrBin: w.herdrBin }), 'no_window')
  assert.equal(loadPending(w.stateDir)?.layout, 'finance-v3')
})
