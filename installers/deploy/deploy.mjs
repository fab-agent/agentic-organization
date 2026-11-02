#!/usr/bin/env node
/**
 * Deployment helper (ADR-0033): install or check ONE user's 3pa workspace from a settings file,
 * the way an MDM, Ansible or a login script would. Runs as the person who will use the workspace
 * (deploy.sh / deploy.ps1 take care of that).
 *
 *   node deploy.mjs install --config deploy.conf [--allow-elevated]
 *   node deploy.mjs check   --config deploy.conf
 *
 * `check` is the MDM "detection rule": exit 0 only if this user has the intended bundle and the
 * intended pinned keys; 1 otherwise (and says why). It changes nothing.
 */
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { existsSync, lstatSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const WIN = process.platform === 'win32'
const die = (m, code = 1) => { console.error(`deploy: ${m}`); process.exit(code) }
const KEYS = ['BASE_URL', 'ROOT_PUB', 'RELEASE_PUB', 'RELEASE_URL', 'CLI_FILE', 'CLI_SHA256', 'HERDR_FILE', 'HERDR_SHA256']

/** KEY=VALUE lines only. Nothing is evaluated, expanded or sourced; unknown keys are an error. */
export function parseConfig(text) {
  const out = {}
  for (const [i, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 1) throw new Error(`line ${i + 1}: expected KEY=VALUE`)
    const k = line.slice(0, eq).trim(), v = line.slice(eq + 1).trim()
    if (!KEYS.includes(k)) throw new Error(`line ${i + 1}: unknown setting ${k}`)
    if (Object.hasOwn(out, k)) throw new Error(`line ${i + 1}: ${k} is set twice`)
    if (/[\x00-\x1f\x7f"'`$\\]/.test(v)) throw new Error(`line ${i + 1}: ${k} contains a character that is not allowed (quotes, $, backslash, control characters)`)
    out[k] = v
  }
  for (const k of ['BASE_URL', 'ROOT_PUB', 'CLI_FILE', 'CLI_SHA256']) if (!out[k]) throw new Error(`${k} is required`)
  if (!/^[0-9a-f]{64}$/.test(out.CLI_SHA256)) throw new Error('CLI_SHA256 must be 64 lowercase hex characters')
  if (!!out.HERDR_FILE !== !!out.HERDR_SHA256) throw new Error('HERDR_FILE and HERDR_SHA256 go together')
  if (out.HERDR_SHA256 && !/^[0-9a-f]{64}$/.test(out.HERDR_SHA256)) throw new Error('HERDR_SHA256 must be 64 lowercase hex characters')
  if (!!out.RELEASE_PUB !== !!out.RELEASE_URL) throw new Error('RELEASE_PUB and RELEASE_URL go together')
  return out
}

const sha = (f) => createHash('sha256').update(readFileSync(f)).digest('hex')
/** A setting that is a file name (relative to the settings file) or the literal base64 key. */
function keyValue(dir, v) {
  const f = path.resolve(dir, v)
  try { if (lstatSync(f).isFile()) return readFileSync(f, 'utf8').replace(/[\r\n ]/g, '') } catch { /* a literal key */ }
  return v.replace(/[\r\n ]/g, '')
}

function locations() {
  const l = WIN ? path.join(process.env.LOCALAPPDATA || path.join(homedir(), 'AppData', 'Local'), '3pa') : path.join(homedir(), '.local')
  return {
    bundle: path.join(l, WIN ? 'lib\\3pa\\3pa.mjs' : 'lib/3pa/3pa.mjs'),
    state: process.env.THREEPA_WORKSPACE_DIR || (WIN ? path.join(l, 'workspace') : path.join(homedir(), '.config', '3pa', 'workspace')),
  }
}

function problems(cfg, dir) {
  const loc = locations(), bad = []
  const read = (f) => { try { return lstatSync(f).isFile() ? readFileSync(f, 'utf8').replace(/[\r\n ]/g, '') : null } catch { return null } }
  try { if (!lstatSync(loc.bundle).isFile() || sha(loc.bundle) !== cfg.CLI_SHA256) bad.push('the installed bundle is not the intended one (it may have been updated by `3pa self-update`, which is fine if a newer signed release is wanted)') } catch { bad.push('the 3pa bundle is not installed') }
  if (read(path.join(loc.state, 'root.pub')) !== keyValue(dir, cfg.ROOT_PUB)) bad.push('the pinned root key is missing or differs')
  if (cfg.RELEASE_PUB) {
    if (read(path.join(loc.state, 'release.pub')) !== keyValue(dir, cfg.RELEASE_PUB)) bad.push('the pinned release key is missing or differs')
    if (read(path.join(loc.state, 'release-url')) !== cfg.RELEASE_URL) bad.push('the release URL is missing or differs')
  }
  return bad
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2)
  const ci = rest.indexOf('--config')
  if (!['install', 'check'].includes(cmd) || ci < 0 || !rest[ci + 1]) die('usage: deploy.mjs install|check --config FILE [--allow-elevated]', 2)
  const confPath = path.resolve(rest[ci + 1]), dir = path.dirname(confPath)
  let cfg
  try { cfg = parseConfig(readFileSync(confPath, 'utf8')) } catch (e) { die(`${confPath}: ${e.message}`, 2) }

  if (cmd === 'check') {
    const bad = problems(cfg, dir)
    if (bad.length) { for (const b of bad) console.log(`not compliant: ${b}`); process.exit(1) }
    console.log('compliant'); return
  }

  const abs = (f) => path.resolve(dir, f)
  const cli = abs(cfg.CLI_FILE)
  if (!existsSync(cli)) die(`${cli} does not exist`, 2)
  const args = [path.join(HERE, '..', 'user', 'windows', 'install.mjs'), '--base-url', cfg.BASE_URL, '--root-pub', keyValue(dir, cfg.ROOT_PUB), '--cli', cli, '--cli-sha256', cfg.CLI_SHA256]
  if (cfg.HERDR_FILE) args.push('--herdr-bin', abs(cfg.HERDR_FILE), '--herdr-sha256', cfg.HERDR_SHA256)
  if (cfg.RELEASE_PUB) args.push('--release-pub', keyValue(dir, cfg.RELEASE_PUB), '--release-url', cfg.RELEASE_URL)
  if (rest.includes('--allow-elevated')) args.push('--allow-elevated')
  // Already as intended? Then do nothing (an MDM runs this on every check-in).
  if (problems(cfg, dir).length === 0) { console.log('already installed as intended; nothing to do'); return }
  const r = spawnSync(process.execPath, args, { stdio: 'inherit' })
  process.exit(r.status ?? 1)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main()
