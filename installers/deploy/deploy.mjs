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

/** The same rule as the installer (https anywhere, http only for loopback, no credentials or
 * fragment) and the same normal form (WHATWG href), so what is compared is what was written. */
export function normUrl(raw, what) {
  let u
  try { u = new URL(raw) } catch { throw new Error(`${what} is not a valid URL`) }
  const loop = u.hostname === 'localhost' || u.hostname === '127.0.0.1' || u.hostname === '[::1]'
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && loop)) throw new Error(`${what} must be https:// (http:// only for localhost)`)
  if (u.username || u.password || u.hash || !u.hostname) throw new Error(`${what} must not contain credentials or a fragment`)
  if (what === 'BASE_URL' && u.search) throw new Error('BASE_URL must not contain a query')
  return u.href
}

/** KEY=VALUE lines only. Nothing is evaluated, expanded or sourced; unknown keys are an error. */
export function parseConfig(text) {
  if (text.length > 64 * 1024) throw new Error('the settings file is too large')
  const out = {}
  for (const [i, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 1) throw new Error(`line ${i + 1}: expected KEY=VALUE`)
    const k = line.slice(0, eq).trim(), v = line.slice(eq + 1).trim()
    if (raw.length > 4096) throw new Error(`line ${i + 1}: too long`)
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
  out.BASE_URL = normUrl(out.BASE_URL, 'BASE_URL')
  if (out.RELEASE_URL) out.RELEASE_URL = normUrl(out.RELEASE_URL, 'RELEASE_URL')
  return out
}

const sha = (f) => createHash('sha256').update(readFileSync(f)).digest('hex')
/** A setting that is a file name (relative to the settings file) or the literal base64 key. */
function keyValue(dir, v, what = 'key') {
  const f = path.resolve(dir, v)
  let s = v
  try { if (lstatSync(f).isFile()) s = readFileSync(f, 'utf8') } catch { /* a literal key */ }
  s = s.replace(/[\r\n ]/g, '')
  const b = Buffer.from(s, 'base64')
  if (b.length !== 32 || b.toString('base64') !== s) throw new Error(`${what} is not a valid Ed25519 public key (32 bytes, canonical base64)`)
  return s
}

function locations() {
  const l = WIN ? path.join(process.env.LOCALAPPDATA || path.join(homedir(), 'AppData', 'Local'), '3pa') : path.join(homedir(), '.local')
  return {
    lib: path.join(l, 'lib', '3pa'), bin: path.join(l, 'bin'),
    bundle: path.join(l, WIN ? 'lib\\3pa\\3pa.mjs' : 'lib/3pa/3pa.mjs'),
    state: process.env.THREEPA_WORKSPACE_DIR || (WIN ? path.join(l, 'workspace') : path.join(homedir(), '.config', '3pa', 'workspace')),
  }
}

/** What differs from the settings. `selfUpdated` = a signed release was accepted on this machine
 * (release-state.json exists): then a bundle/binary that differs from the BOOTSTRAP hashes is the
 * product of `3pa self-update`, not drift, and an install must never put the old one back. */
function problems(cfg, dir) {
  const loc = locations(), bad = [], keep = []
  const read = (f) => { try { return lstatSync(f).isFile() ? readFileSync(f, 'utf8').replace(/[\r\n ]/g, '') : null } catch { return null } }
  const hashOf = (f) => { try { return lstatSync(f).isFile() ? sha(f) : null } catch { return null } }
  const selfUpdated = existsSync(path.join(loc.state, 'release-state.json'))
  const artifact = (label, file, want) => {
    const have = hashOf(file)
    if (have === null) bad.push(`${label} is not installed`)
    else if (have !== want) (selfUpdated ? keep : bad).push(selfUpdated ? `${label} is newer than the settings (installed by 3pa self-update); kept` : `the installed ${label} is not the intended one`)
  }
  artifact('the 3pa bundle', loc.bundle, cfg.CLI_SHA256)
  if (cfg.HERDR_FILE) {
    artifact('Herdr', path.join(loc.lib, WIN ? 'herdr.exe' : 'herdr'), cfg.HERDR_SHA256)
    if (hashOf(path.join(loc.bin, WIN ? 'herdr-fab.cmd' : 'herdr-fab')) === null) bad.push('the herdr-fab launcher is not installed')
  }
  if (read(path.join(loc.state, 'root.pub')) !== keyValue(dir, cfg.ROOT_PUB, 'ROOT_PUB')) bad.push('the pinned root key is missing or differs')
  if (cfg.RELEASE_PUB) {
    if (read(path.join(loc.state, 'release.pub')) !== keyValue(dir, cfg.RELEASE_PUB, 'RELEASE_PUB')) bad.push('the pinned release key is missing or differs')
    if (read(path.join(loc.state, 'release-url')) !== cfg.RELEASE_URL) bad.push('the release URL is missing or differs')
  }
  return { bad, keep, selfUpdated }
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2)
  const ci = rest.indexOf('--config')
  if (!['install', 'check'].includes(cmd) || ci < 0 || !rest[ci + 1]) die('usage: deploy.mjs install|check --config FILE [--pins-only] [--allow-elevated]', 2)
  if (/[\x00-\x1f\x7f]/.test(rest[ci + 1])) die('the settings file path must not contain control characters', 2)
  const confPath = path.resolve(rest[ci + 1]), dir = path.dirname(confPath)
  let cfg
  try { cfg = parseConfig(readFileSync(confPath, 'utf8')) } catch (e) { die(`${confPath}: ${e.message}`, 2) }
  let state
  try { state = problems(cfg, dir) } catch (e) { die(`${confPath}: ${e.message}`, 2) }

  if (cmd === 'check') {
    // --pins-only: the trust setup only (keys, release URL); a newer or different bundle is not drift
    const bad = rest.includes('--pins-only') ? state.bad.filter((b) => /pinned|release URL/.test(b)) : state.bad
    if (bad.length) { for (const b of bad) console.log(`not compliant: ${b}`); process.exit(1) }
    for (const k of state.keep) console.log(`note: ${k}`)
    console.log('compliant'); return
  }

  if (state.bad.length === 0) { console.log('already installed as intended; nothing to do'); for (const k of state.keep) console.log(`note: ${k}`); return }
  const abs = (f) => path.resolve(dir, f)
  const cli = abs(cfg.CLI_FILE)
  if (!existsSync(cli)) die(`${cli} does not exist`, 2)
  const loc = locations()
  const herdrPath = path.join(loc.lib, WIN ? 'herdr.exe' : 'herdr')
  const installedOk = (f) => { try { return lstatSync(f).isFile() } catch { return false } }
  // After a signed update, the INSTALLED bundle/binary is the source (re-installed onto itself, so
  // only the missing pieces change); otherwise the ones named in the settings.
  const keepBundle = state.selfUpdated && installedOk(loc.bundle)
  const keepHerdr = state.selfUpdated && installedOk(herdrPath)
  const args = [path.join(HERE, '..', 'user', 'windows', 'install.mjs'), '--base-url', cfg.BASE_URL, '--root-pub', keyValue(dir, cfg.ROOT_PUB, 'ROOT_PUB'),
    '--cli', keepBundle ? loc.bundle : cli, '--cli-sha256', keepBundle ? sha(loc.bundle) : cfg.CLI_SHA256,
    '--state-dir', loc.state] // the same place `check` looks at, even when THREEPA_WORKSPACE_DIR is set
  if (cfg.HERDR_FILE) args.push('--herdr-bin', keepHerdr ? herdrPath : abs(cfg.HERDR_FILE), '--herdr-sha256', keepHerdr ? sha(herdrPath) : cfg.HERDR_SHA256)
  if (cfg.RELEASE_PUB) args.push('--release-pub', keyValue(dir, cfg.RELEASE_PUB, 'RELEASE_PUB'), '--release-url', cfg.RELEASE_URL)
  if (rest.includes('--allow-elevated')) args.push('--allow-elevated')
  if (state.selfUpdated) {
    // Never put an older bootstrap bundle over one that `3pa self-update` installed. Only what is
    // MISSING is added; to go back, publish a newer signed release.
    console.error('deploy: a signed update is already installed here; installing only what is missing (an existing newer bundle/binary is not replaced)')
  }
  const r = spawnSync(process.execPath, args, { stdio: 'inherit' })
  process.exit(r.status ?? 1)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main()
