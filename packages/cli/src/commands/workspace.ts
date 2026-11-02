/**
 * `3pa workspace` (ADR-0029) - put this person's signed Herdr workspace in place.
 *
 *   3pa workspace sync   [--base URL] [--company ID] [--root-pub FILE|BASE64]
 *                        [--app-home DIR] [--oidc ID_TOKEN] [--adopt] [--re-enroll]
 *   3pa workspace status [--app-home DIR]
 *   3pa workspace report [--base URL] [--company ID] [--app-home DIR]   (drift as counts, ADR-0035)
 *
 * `sync` signs in (the web token stays in memory), asks the platform for the manifest of
 * the signed-in person, verifies it against the root key pinned on this machine, and
 * installs the layout and mods into the Herdr app home. The root public key comes from the
 * installer / MDM (`--root-pub`, FABAGENT_WORKSPACE_ROOT_PUB, or <state dir>/root.pub);
 * it is never fetched from the server. For unattended use set FABAGENT_WEB_TOKEN.
 */

import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import * as p from '@clack/prompts'
import chalk from 'chalk'

import { ReportError, sendReport } from '../utils/drift-report.js'
import { ProvisionError, checkBaseUrl, scanDrift, syncWorkspace } from '../utils/provisioner.js'
import { StateError, loadState, workspaceStateDir } from '../utils/workspace-state.js'
import { loadSession, webSignIn } from './login.js'

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i !== -1 ? args[i + 1] : undefined
}

function appHome(args: string[]): string {
  const dflt = process.platform === 'win32' ? join(process.env.APPDATA || join(homedir(), 'AppData', 'Roaming'), 'herdr-app') : join(homedir(), '.config', 'herdr-app')
  return flag(args, '--app-home') || process.env.HERDR_APP_HOME || dflt
}

/** A file path, or the base64 key itself. */
function rootPub(args: string[]): string {
  const v = flag(args, '--root-pub') || process.env.FABAGENT_WORKSPACE_ROOT_PUB
  if (v) return existsSync(v) ? readFileSync(v, 'utf8').trim() : v.trim()
  const file = join(workspaceStateDir(), 'root.pub')
  if (existsSync(file)) return readFileSync(file, 'utf8').trim()
  throw new ProvisionError('root_pub_missing', 'no root public key: the installer places it in ' + file)
}

const MESSAGES: Record<string, string> = {
  root_pub_missing: 'Root public key not found (the installer or your administrator provides it).',
  unmanaged_exists: 'A layout or mod with that name already exists and was not installed by 3pa. Rename it, or run with --adopt to let 3pa replace it.',
  shipped_name: 'The workspace uses a name Herdr ships itself; ask your administrator to rename it.',
  identity_changed: 'The server answered for a different person than this machine was set up for. Use --re-enroll only if that is intended.',
  state_corrupt: 'The local sync state is damaged. It is not reset on its own (that would allow an old workspace to be replayed). Use --re-enroll to start over.',
  locked: 'Another workspace sync is already running.',
  settings_invalid: 'Herdr settings.json is not valid JSON; fix or remove it, then run again.',
  recovery_required: 'An update was interrupted and could not be rolled back completely. The previous items were kept (see the message); do not delete them. Run the sync again once the cause is fixed.',
  base_url_insecure: 'The platform URL must be https:// (http:// is accepted only for localhost).',
  base_url_invalid: 'The platform URL is not valid (no credentials, query or fragment allowed).',
  lock_lost: 'The sync lock was taken over by another run; nothing further was written. Run the sync again.',
  state_unreadable: 'The local sync state could not be read (a disk or permission problem). Nothing was changed; fix the cause and run again.',
  fs_error: 'A file operation failed unexpectedly. Run `3pa workspace status` to see where things stand; running the sync again is safe.',
  state_not_recorded: 'The workspace was updated, but the sync state could not be saved. Run the sync again.',
  locking_unsupported: 'The state directory is on a file system without hard links. Point THREEPA_WORKSPACE_DIR at a normal local folder.',
  sync_timeout: 'The sync took too long (or the platform did not answer) and was stopped; no new update was applied. Run the sync again.',
  bad_duration: 'The time limit given to the sync is not valid.',
  app_home_unsafe: 'The Herdr app home contains a link where a real folder is expected; it was left untouched.',
}

export async function workspace(args: string[]): Promise<void> {
  const sub = args[0]
  if (sub === 'status') return status(args.slice(1))
  if (sub === 'sync') return sync(args.slice(1))
  if (sub === 'report') return report(args.slice(1))
  console.log('  ' + chalk.bold('Kullanım:') + '  3pa workspace sync | status | report')
  if (sub) process.exit(1)
}

async function sync(args: string[]): Promise<void> {
  p.intro(chalk.bold('3pa workspace sync'))
  try {
    const base = checkBaseUrl(flag(args, '--base') || process.env.FABAGENT_BASE_URL || loadSession()?.base_url || '')
    const pub = rootPub(args)
    const webToken = process.env.FABAGENT_WEB_TOKEN || (await webSignIn(base, args))
    if (webToken === null) return void p.cancel('cancelled')
    const r = await syncWorkspace({
      baseUrl: base,
      webToken,
      companyId: flag(args, '--company'),
      rootPub: pub,
      appHome: appHome(args),
      stateDir: workspaceStateDir(),
      clientVersion: process.env.THREEPA_VERSION || '1.0.0',
      adopt: args.includes('--adopt'),
      reEnroll: args.includes('--re-enroll'),
    })
    p.outro(
      chalk.green(r.status === 'updated' ? 'Workspace updated' : 'Workspace already up to date') +
        chalk.dim(`  generation ${r.generation}, layout ${r.layout}, mods: ${r.mods.join(', ') || '-'}`),
    )
    // Best effort and never part of the sync's result: a report that cannot be sent is one dim line.
    if (!args.includes('--no-report') && !process.env.THREEPA_NO_REPORT) {
      try {
        const out = await sendReport({ baseUrl: base, webToken, companyId: flag(args, '--company'), appHome: appHome(args), stateDir: workspaceStateDir(), clientVersion: process.env.THREEPA_VERSION || '1.0.0' })
        console.log(chalk.dim(out === 'sent' ? '  status report sent' : out === 'too_soon' ? '  status report skipped (sent a moment ago)' : '  nothing installed, nothing to report'))
      } catch (e) {
        console.log(chalk.dim(`  status report not sent [${e instanceof ReportError ? e.code : 'error'}]`))
      }
    }
  } catch (e) {
    const code = e instanceof ProvisionError || e instanceof StateError ? e.code : 'error'
    const known = e instanceof ProvisionError || e instanceof StateError
    const hint =
      MESSAGES[code] ??
      (code.startsWith('manifest_') ? 'The manifest was refused (' + code.slice(9) + '); nothing was installed.'
        : code.startsWith('server_') ? 'The platform cannot issue a workspace right now (' + code.slice(7) + ').'
        : known ? (e as Error).message
        : process.env.THREEPA_DEBUG ? (e as Error).message : 'Unexpected error (set THREEPA_DEBUG=1 for details).')
    p.cancel(chalk.red(hint) + chalk.dim(`  [${code}]`))
    process.exit(1)
  }
}

async function report(args: string[]): Promise<void> {
  p.intro(chalk.bold('3pa workspace report'))
  try {
    const base = checkBaseUrl(flag(args, '--base') || process.env.FABAGENT_BASE_URL || loadSession()?.base_url || '')
    const webToken = process.env.FABAGENT_WEB_TOKEN || (await webSignIn(base, args))
    if (webToken === null) return void p.cancel('cancelled')
    const out = await sendReport({ baseUrl: base, webToken, companyId: flag(args, '--company'), appHome: appHome(args), stateDir: workspaceStateDir(), clientVersion: process.env.THREEPA_VERSION || '1.0.0' })
    p.outro(
      out === 'sent' ? chalk.green('Status report sent') + chalk.dim('  (counts only; a claim, not proof)')
        : out === 'too_soon' ? chalk.yellow('A report was sent a moment ago; try again in 30 seconds')
        : chalk.yellow('Nothing is installed yet; run `3pa workspace sync` first'),
    )
  } catch (e) {
    const code = e instanceof ReportError || e instanceof ProvisionError || e instanceof StateError ? e.code : 'error'
    p.cancel(chalk.red(e instanceof ReportError ? `The report could not be sent (${code}).` : (MESSAGES[code] ?? 'Unexpected error (set THREEPA_DEBUG=1 for details).')) + chalk.dim(`  [${code}]`))
    process.exit(1)
  }
}

function status(args: string[]): void {
  const home = appHome(args)
  let st
  try {
    st = loadState(workspaceStateDir())
  } catch (e) {
    console.log(chalk.red(`  state: ${(e as StateError).code}`))
    process.exit(1)
  }
  if (!st?.installed) {
    console.log('  No workspace installed yet. Run ' + chalk.cyan('3pa workspace sync') + '.')
    return
  }
  console.log(`  generation ${st.installed.generation}, epoch ${st.installed.epoch}`)
  const d = scanDrift(home)
  if (d.interrupted) console.log('  ' + chalk.yellow('An update was interrupted; run 3pa workspace sync to finish rolling it back.'))
  const lines = [
    ...d.missing.map((x) => `missing   ${x}`),
    ...d.modified.map((x) => `modified  ${x}`),
    ...d.extraFiles.map((x) => `extra     ${x}`),
    ...d.unmanagedMods.map((x) => `unmanaged mod  ${x}`),
  ]
  if (lines.length === 0) console.log('  ' + chalk.green('No drift from the installed workspace.'))
  else {
    console.log('  ' + chalk.yellow('Differences (a diagnostic, not proof of tampering):'))
    for (const l of lines) console.log('    ' + l)
    process.exit(2)
  }
}
