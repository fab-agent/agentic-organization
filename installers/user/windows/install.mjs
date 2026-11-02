#!/usr/bin/env node
/**
 * User installer for Windows (ADR-0032); also runs on Linux/macOS, where it behaves like
 * install.sh and is tested that way. Node.js 20+ is the only dependency (3pa needs it anyway).
 *
 *   node install.mjs --base-url URL --root-pub FILE|BASE64 --cli FILE --cli-sha256 HEX
 *        [--herdr-bin FILE --herdr-sha256 HEX] [--release-pub FILE|BASE64 --release-url URL]
 *        [--replace-release-key] [--prefix DIR] [--app-home DIR] [--state-dir DIR]
 *        [--replace-root] [--dry-run] [--allow-elevated]
 *   node install.mjs --uninstall [--prefix DIR] [--state-dir DIR] [--purge-state]
 *
 * Same contract as install.sh: it downloads nothing, checks every hash on the COPY, pins the
 * keys (never replacing one without an explicit flag), refuses unsafe locations, never
 * deletes recursively, and the launcher fails closed.
 */
import { createHash, randomBytes } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import {
  chmodSync, closeSync, copyFileSync, fsyncSync, lstatSync, mkdirSync, openSync, readFileSync,
  readdirSync, realpathSync, renameSync, rmSync, rmdirSync, statSync, unlinkSync, writeFileSync,
} from 'node:fs'
import { homedir, userInfo } from 'node:os'
import path from 'node:path'

const WIN = process.platform === 'win32'
const P = WIN ? path.win32 : path.posix
const EXE = WIN ? '.exe' : ''
// Windows tools are run by absolute path: a `whoami` or `icacls` earlier on PATH (Git for Windows
// ships a different whoami, for one) must never be the one that decides who the user is.
const SYS32 = P.join(process.env.SystemRoot || process.env.windir || 'C:\\Windows', 'System32')
const sys = (exe) => P.join(SYS32, exe)

class Fail extends Error {}
const die = (m) => { throw new Fail(m) }
const say = (m) => console.log('  ' + m)

// ── arguments ────────────────────────────────────────────────────────────────
const VALUE_OPTS = ['--base-url', '--root-pub', '--cli', '--cli-sha256', '--herdr-bin', '--herdr-sha256', '--release-pub', '--release-url', '--prefix', '--app-home', '--state-dir']
const FLAG_OPTS = ['--allow-elevated', '--replace-root', '--replace-release-key', '--dry-run', '--uninstall', '--purge-state']

function parseArgs(argv) {
  const o = {}
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (VALUE_OPTS.includes(a)) {
      if (i + 1 >= argv.length) die(`${a} needs a value`)
      o[a] = argv[++i]
    } else if (FLAG_OPTS.includes(a)) o[a] = true
    else if (a === '-h' || a === '--help') { console.log(readFileSync(new URL(import.meta.url), 'utf8').split('\n').slice(2, 14).join('\n')); process.exit(0) }
    else die(`unknown option: ${a}`)
  }
  return o
}

// ── helpers ──────────────────────────────────────────────────────────────────
const sha256 = (file) => createHash('sha256').update(readFileSync(file)).digest('hex')
const HEX64 = /^[0-9a-f]{64}$/
const isKey = (s) => { const b = Buffer.from(s, 'base64'); return b.length === 32 && b.toString('base64') === s }

function look(p) {
  try { return lstatSync(p) } catch (e) {
    if (e.code === 'ENOENT' || e.code === 'ENOTDIR') return null
    die(`cannot inspect ${p} (${e.code}); nothing was changed`)
  }
}

/** The deepest part of the path that exists is resolved (links, junctions, 8.3 names); the rest
 * is appended as written. */
function real(p) {
  let head = P.resolve(p); const tail = []
  for (;;) {
    try { return P.join(WIN ? realpathSync.native(head) : realpathSync(head), ...tail.reverse()) } catch (e) {
      if (e.code !== 'ENOENT' && e.code !== 'ENOTDIR') throw e
      const up = P.dirname(head); if (up === head) return head
      tail.push(P.basename(head)); head = up
    }
  }
}

const norm = (p) => (WIN ? p.toLowerCase() : p)
const within = (a, b) => { a = norm(a); b = norm(b); return a === b || a.startsWith(b.endsWith(P.sep) ? b : b + P.sep) }

const RESERVED = /^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$/i

/** Judge the raw text of a location BEFORE anything normalises it. */
function checkRaw(label, v) {
  if (/[\x00-\x1f\x7f]/.test(v)) die(`${label} path must not contain control characters (newline, tab, ...)`)
  if (!WIN && v.includes('\\')) die(`${label} path must not contain backslashes`)
  if (v.split(/[\\/]/).includes('..')) die(`${label} path must not contain ..`)
  try { new TextDecoder('utf-8', { fatal: true }).decode(Buffer.from(v, 'utf8')) } catch { die(`${label} path must be valid text`) }
  if (!P.isAbsolute(v)) die(`${label} path must be absolute`)
  if (WIN) {
    if (!/^[A-Za-z]:[\\/]/.test(v)) die(`${label} path must start with a drive letter (UNC and \\\\?\\ paths are not supported)`)
    if (/[<>"|?*%]/.test(v.slice(2))) die(`${label} path must not contain < > " | ? * or %`)
    if (v.slice(2).includes(':')) die(`${label} path must not contain ":" (alternate data streams)`)
    for (const c of v.slice(3).split(/[\\/]+/).filter(Boolean)) {
      if (RESERVED.test(c)) die(`${label} path contains a reserved device name (${c})`)
      if (/[. ]$/.test(c)) die(`${label} path components must not end with a dot or a space`)
    }
  }
}

/** Drop repeated, trailing and `.` components so every check and every write names the same thing. */
function clean(v) {
  const root = P.parse(v).root
  const parts = v.slice(root.length).split(/[\\/]+/).filter((c) => c && c !== '.')
  return root + parts.join(P.sep)
}

function checkLocations(o) {
  const home = real(homedir())
  const spots = {
    bin: real(P.join(o.prefix, 'bin')), lib: real(P.join(o.prefix, 'lib', '3pa')),
    state: real(o.state), 'app home': real(o.app),
  }
  for (const [k, v] of Object.entries(spots)) {
    if (v === P.parse(v).root || norm(v) === norm(home) || within(home, v)) die(`${k} location may not be the drive root, your home directory or a parent of it`)
  }
  const names = Object.keys(spots)
  for (let i = 0; i < names.length; i++) for (let j = i + 1; j < names.length; j++) {
    if (within(spots[names[i]], spots[names[j]]) || within(spots[names[j]], spots[names[i]])) {
      die(`${names[i]} and ${names[j]} locations overlap; choose separate folders`)
    }
  }
}

function checkUrl(raw, what, allowQueryPath) {
  let u
  try { u = new URL(raw) } catch { die(`${what} is not a valid platform URL (no credentials, query or fragment)`) }
  const loop = u.hostname === 'localhost' || u.hostname === '127.0.0.1' || u.hostname === '[::1]'
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && loop)) die(`${what} must be https:// (http:// is accepted only for localhost)`)
  if (u.username || u.password || u.hash || !u.hostname || (!allowQueryPath && u.search)) die(`${what} is not a valid platform URL (no credentials, query or fragment)`)
  return allowQueryPath ? u.href : u.origin + u.pathname.replace(/\/+$/, '')
}

function readKey(v, label) {
  let s = v
  try { if (statSync(v).isFile()) s = readFileSync(v, 'utf8') } catch { /* a literal key */ }
  s = s.replace(/[\r\n ]/g, '')
  if (!isKey(s)) die(`${label} is not a valid Ed25519 public key (32 bytes, canonical base64)`)
  return s
}

/** The key pinned under `name` in the state folder ("" when none). "Cannot look" never means "not there". */
function pinnedOf(stateDir, name) {
  const d = look(stateDir)
  if (!d) return ''
  if (d.isSymbolicLink() || !d.isDirectory()) die(`${stateDir} is a link or not a folder; nothing was changed`)
  if (typeof process.getuid === 'function' && d.uid !== process.getuid()) die(`${stateDir} belongs to someone else; nothing was changed`)
  const f = P.join(stateDir, name)
  const s = look(f)
  if (!s) return ''
  if (!s.isFile()) die(`${f} is not a regular file; nothing was changed`)
  try { return readFileSync(f, 'utf8').replace(/[\r\n ]/g, '') } catch (e) { die(`cannot read the pinned key (${e.code}); nothing was changed`) }
}

function checkPlain(f) {
  const s = look(f)
  if (s && (s.isSymbolicLink() || !s.isFile())) die(`${f} exists and is not a plain file; nothing was changed`)
}

// temp files we create are removed on any failure
const temps = new Set()
function stageCopy(src, dest, want, label) {
  const tmp = P.join(P.dirname(dest), `.${P.basename(dest)}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`)
  temps.add(tmp); rmSync(tmp, { force: true })
  copyFileSync(src, tmp)
  if (sha256(tmp) !== want) die(`SHA-256 of ${label} does not match; nothing was installed`)
  return tmp
}
function publish(tmp, dest) { renameSync(tmp, dest); temps.delete(tmp) }
function writeText(dest, text, mode = 0o644) {
  const tmp = P.join(P.dirname(dest), `.${P.basename(dest)}.${process.pid}.tmp`)
  temps.add(tmp)
  const fd = openSync(tmp, 'w', mode); try { writeFileSync(fd, text); fsyncSync(fd) } finally { closeSync(fd) }
  if (!WIN) chmodSync(tmp, mode)
  renameSync(tmp, dest); temps.delete(tmp)
}

/** Windows has no 0700: take the folder away from everyone but the current user. */
function privateAcl(dir) {
  if (!WIN) { chmodSync(dir, 0o700); return }
  const sid = execFileSync(sys('whoami.exe'), ['/user', '/fo', 'csv', '/nh'], { encoding: 'utf8' }).trim().split(',')[1]?.replace(/"/g, '')
  if (!sid || !/^S-1-[0-9-]+$/.test(sid)) die('could not determine the current user to restrict the state folder')
  execFileSync(sys('icacls.exe'), [dir, '/inheritance:r', '/grant:r', `*${sid}:(OI)(CI)F`], { stdio: 'ignore' })
}

function notElevated(allow) {
  if (allow) return // explicit: CI runners and deliberate installs into an administrator's own profile
  if (WIN) {
    let g = ''
    try { g = execFileSync(sys('whoami.exe'), ['/groups'], { encoding: 'utf8' }) } catch { die('could not check whether this prompt is elevated; fix that, or pass --allow-elevated if you are sure') }
    if (g.includes('S-1-16-12288')) die('run as the person who will use the workspace, not from an elevated (administrator) prompt')
  } else if (process.getuid && process.getuid() === 0) die('run as the person who will use the workspace, not as root')
}

const OURS = [/^root\.pub$/, /^state\.json$/, /^state\.json\.replaced-\d+$/, /^state\.json\.[0-9a-f]{12}\.tmp$/,
  /^sync\.lock$/, /^sync\.lock\.takeover$/, /^sync\.lock(\.takeover)?\.tmp-[0-9a-f]{12}$/, /^\.root\.pub\.\d+\.tmp$/,
  /^release\.pub$/, /^release-url$/, /^release-state\.json$/, /^release-state\.json\.[0-9a-f]{12}\.tmp$/,
  /^\.release\.pub\.\d+\.tmp$/, /^\.release-url\.\d+\.tmp$/]

const q = (s) => `"${s}"` // paths cannot contain " or % (checkRaw), so this is safe in a .cmd file

// ── main ─────────────────────────────────────────────────────────────────────
function main() {
  const a = parseArgs(process.argv.slice(2))
  notElevated(!!a['--allow-elevated'])
  const uninstall = !!a['--uninstall']
  if (uninstall && a['--dry-run']) die('--dry-run applies to installing only; nothing was removed')
  if (!uninstall && a['--purge-state']) die('--purge-state belongs to --uninstall')

  const home = homedir()
  const dflt = WIN ? P.join(process.env.LOCALAPPDATA || P.join(home, 'AppData', 'Local'), '3pa') : P.join(home, '.local')
  const raw = {
    prefix: a['--prefix'] ?? dflt,
    state: a['--state-dir'] ?? (WIN ? P.join(dflt, 'workspace') : P.join(home, '.config', '3pa', 'workspace')),
    app: a['--app-home'] ?? (WIN ? P.join(process.env.APPDATA || P.join(home, 'AppData', 'Roaming'), 'herdr-app') : P.join(home, '.config', 'herdr-app')),
  }
  checkRaw('prefix', raw.prefix); checkRaw('state', raw.state); checkRaw('app home', raw.app)
  const o = { prefix: clean(raw.prefix), state: clean(raw.state), app: clean(raw.app) }
  checkLocations(o)
  const BIN = P.join(o.prefix, 'bin'), LIB = P.join(o.prefix, 'lib', '3pa')
  const wrapper = P.join(BIN, WIN ? '3pa.cmd' : '3pa'), launcher = P.join(BIN, WIN ? 'herdr-fab.cmd' : 'herdr-fab')
  const herdrDest = P.join(LIB, `herdr${EXE}`)

  if (uninstall) {
    for (const f of [wrapper, launcher]) if (look(f)) { rmSync(f, { force: true }); say(`removed ${f}`) }
    for (const f of [P.join(LIB, '3pa.mjs'), herdrDest]) { const s = look(f); if (s && (s.isFile() || s.isSymbolicLink())) unlinkSync(f) }
    const ls = look(LIB)
    if (ls?.isSymbolicLink()) say(`kept ${LIB} (a link; its target was not removed, remove the link yourself if you want)`)
    else if (ls?.isDirectory()) {
      try { rmdirSync(LIB); say(`removed ${LIB}`) } catch (e) {
        if (e.code === 'ENOTEMPTY' || e.code === 'EEXIST') say(`kept ${LIB} (it holds files that are not ours)`)
        else die(`could not remove the empty folder ${LIB} (${e.code})`)
      }
    }
    if (a['--purge-state']) purge(o.state)
    else say(`kept ${o.state} (root key and sync history; --purge-state removes it)`)
    say(`left the Herdr app home alone: ${o.app}`)
    return
  }

  for (const k of ['--base-url', '--root-pub']) if (!a[k]) die(`${k} is required`)
  if (!a['--cli'] || !a['--cli-sha256']) die('--cli and --cli-sha256 are required')
  if (!!a['--herdr-bin'] !== !!a['--herdr-sha256']) die('--herdr-bin and --herdr-sha256 go together')
  if (!!a['--release-pub'] !== !!a['--release-url']) die('--release-pub and --release-url go together')
  const base = checkUrl(a['--base-url'], '--base-url', false)
  if (!HEX64.test(a['--cli-sha256'])) die('--cli-sha256 must be 64 lowercase hex characters')
  if (a['--herdr-sha256'] && !HEX64.test(a['--herdr-sha256'])) die('--herdr-sha256 must be 64 lowercase hex characters')
  const rootPub = readKey(a['--root-pub'], '--root-pub')
  const relPub = a['--release-pub'] ? readKey(a['--release-pub'], '--release-pub') : ''
  const relUrl = a['--release-url'] ? checkUrl(a['--release-url'], '--release-url', true) : ''
  for (const [k, f] of [['--cli', a['--cli']], ['--herdr-bin', a['--herdr-bin']]]) {
    if (!f) continue
    const s = look(f)
    if (!s || s.isSymbolicLink() || !s.isFile()) die(`${k} must be a regular file`)
  }

  const prevRoot = pinnedOf(o.state, 'root.pub')
  if (prevRoot && prevRoot !== rootPub && !a['--replace-root']) die(`a different root key is already pinned in ${P.join(o.state, 'root.pub')}; pass --replace-root only if the change is intended`)
  if (relPub) {
    const prevRel = pinnedOf(o.state, 'release.pub')
    if (prevRel && prevRel !== relPub && !a['--replace-release-key']) die(`a different release key is already pinned in ${P.join(o.state, 'release.pub')}; pass --replace-release-key only if the change is intended`)
  }
  for (const f of [P.join(LIB, '3pa.mjs'), herdrDest, wrapper, launcher]) checkPlain(f)
  if (relUrl) checkPlain(P.join(o.state, 'release-url'))

  if (a['--dry-run']) { say(`dry run: would install into ${o.prefix} (cli${a['--herdr-bin'] ? ', herdr, launcher' : ''}), state ${o.state}`); return }

  // Stage every artifact first; nothing goes live until all hashes match.
  mkdirSync(BIN, { recursive: true }); mkdirSync(LIB, { recursive: true })
  const cliTmp = stageCopy(a['--cli'], P.join(LIB, '3pa.mjs'), a['--cli-sha256'], a['--cli'])
  const herdrTmp = a['--herdr-bin'] ? stageCopy(a['--herdr-bin'], herdrDest, a['--herdr-sha256'], a['--herdr-bin']) : null
  if (!WIN) { chmodSync(cliTmp, 0o755); if (herdrTmp) chmodSync(herdrTmp, 0o755) }

  mkdirSync(o.state, { recursive: true }); privateAcl(o.state)
  publish(cliTmp, P.join(LIB, '3pa.mjs')); say(`installed 3pa bundle -> ${P.join(LIB, '3pa.mjs')}`)
  writeText(wrapper, WIN ? ['@echo off', `if not defined THREEPA_WORKSPACE_DIR set "THREEPA_WORKSPACE_DIR=${o.state}"`, `if not defined HERDR_APP_HOME set "HERDR_APP_HOME=${o.app}"`, `node ${q(P.join(LIB, '3pa.mjs'))} %*`, ''].join('\r\n') : `#!/bin/sh\n[ -n "\${THREEPA_WORKSPACE_DIR:-}" ] || THREEPA_WORKSPACE_DIR='${o.state}'; export THREEPA_WORKSPACE_DIR\n[ -n "\${HERDR_APP_HOME:-}" ] || HERDR_APP_HOME='${o.app}'; export HERDR_APP_HOME\nexec node '${P.join(LIB, '3pa.mjs')}' "$@"\n`, 0o755)
  say(`installed ${wrapper}`)
  writeText(P.join(o.state, 'root.pub'), rootPub + '\n'); say(`pinned root key -> ${P.join(o.state, 'root.pub')}`)
  if (relPub) {
    writeText(P.join(o.state, 'release.pub'), relPub + '\n'); writeText(P.join(o.state, 'release-url'), relUrl + '\n')
    say(`pinned release key and URL -> ${P.join(o.state, 'release.pub')} (update with: 3pa self-update)`)
  }
  if (herdrTmp) {
    publish(herdrTmp, herdrDest); say(`installed Herdr -> ${herdrDest}`)
    const url = base.replace(/%/g, '%%')
    writeText(launcher, WIN
      ? ['@echo off', 'setlocal', `set "FABAGENT_BASE_URL=${url}"`, `set "THREEPA_WORKSPACE_DIR=${o.state}"`, `set "HERDR_APP_HOME=${o.app}"`,
        `call ${q(wrapper)} workspace sync`,
        'if errorlevel 1 (', '  echo herdr-fab: the workspace could not be synced and verified; not starting Herdr. 1>&2', '  exit /b 1', ')',
        `${q(herdrDest)} %*`, 'exit /b %errorlevel%', ''].join('\r\n')
      : `#!/bin/sh\nset -eu\nexport FABAGENT_BASE_URL='${base.replace(/'/g, "'\\''")}'\nexport THREEPA_WORKSPACE_DIR='${o.state}'\nexport HERDR_APP_HOME='${o.app}'\n'${wrapper}' workspace sync || { echo "herdr-fab: the workspace could not be synced and verified; not starting Herdr." >&2; exit 1; }\nexec '${herdrDest}' "$@"\n`, 0o755)
    say(`installed launcher ${launcher}`)
  } else say('no Herdr binary given: installed the CLI and the root key only')
  say(`done. First start: ${herdrTmp ? 'herdr-fab' : '3pa workspace sync'} (it asks you to sign in). Add ${BIN} to your PATH if it is not there.`)
}

function purge(state) {
  const d = look(state)
  if (!d) { say(`no state folder at ${state}`); return }
  if (d.isSymbolicLink() || !d.isDirectory()) die(`${state} is a link or not a folder; nothing was removed`)
  if (typeof process.getuid === 'function' && d.uid !== process.getuid()) die(`${state} belongs to someone else; nothing was removed`)
  let names
  try { names = readdirSync(state) } catch (e) { die(`cannot read ${state} (${e.code}); nothing was removed`) }
  let removed = 0, left = 0
  for (const n of names) {
    if (!OURS.some((r) => r.test(n))) { left++; continue }
    const p = P.join(state, n)
    const s = look(p)
    if (!s || !s.isFile()) { left++; say(`left ${p} (not a regular file)`); continue }
    try { unlinkSync(p); removed++ } catch (e) { die(`cannot remove ${p} (${e.code})`) }
  }
  try { rmdirSync(state); say(`removed ${state} (${removed} files: root key and sync history)`) } catch (e) {
    if (e.code === 'ENOTEMPTY' || e.code === 'EEXIST') say(`removed ${removed} file(s) of ours from ${state}; kept the folder (${left} other entries)`)
    else die(`removed ${removed} file(s) but could not remove the folder ${state} (${e.code})`)
  }
}

try { main() } catch (e) {
  for (const t of temps) { try { rmSync(t, { force: true }) } catch { /* best effort */ } }
  if (e instanceof Fail) { console.error(`install: ${e.message}`); process.exit(1) }
  throw e
}
for (const t of temps) { try { rmSync(t, { force: true }) } catch { /* best effort */ } }
