import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { test } from 'node:test'

import { parseRunArgs } from '../src/commands/run.ts'

test('defaults: cwd project, egress on, verify on, build on', () => {
  const o = parseRunArgs([])
  assert.equal(o.projectDir, process.cwd())
  assert.equal(o.egress, true)
  assert.equal(o.verify, true)
  assert.equal(o.build, true)
  assert.equal(o.acceptKeyChange, false)
})

test('positional project dir is resolved to absolute', () => {
  assert.equal(parseRunArgs(['.']).projectDir, resolve('.'))
})

test('flags parse', () => {
  const o = parseRunArgs([
    '--no-egress',
    '--no-verify',
    '--no-build',
    '--accept-key-change',
    '--model',
    'fabagent/qwen-max',
    '--allow',
    'git.corp,foo.io',
    'proj',
  ])
  assert.equal(o.egress, false)
  assert.equal(o.verify, false)
  assert.equal(o.build, false)
  assert.equal(o.acceptKeyChange, true)
  assert.equal(o.model, 'fabagent/qwen-max')
  assert.equal(o.allow, 'git.corp,foo.io')
  assert.equal(o.projectDir, resolve('proj'))
})

test('unknown flag throws', () => {
  assert.throws(() => parseRunArgs(['--nope']), /unknown flag/)
})
