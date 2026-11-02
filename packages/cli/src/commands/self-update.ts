/**
 * `3pa self-update` (ADR-0031) - replace the installed `3pa` (and Herdr) with a release that
 * was signed offline with the pinned release key.
 *
 *   3pa self-update [--check] [--release-url URL] [--release-pub FILE|BASE64]
 *                   [--lib-dir DIR] [--channel NAME]
 *
 * The release key and the manifest URL come from the installer (<state dir>/release.pub and
 * <state dir>/release-url) or, for a one-off, from the flags / THREEPA_RELEASE_URL /
 * THREEPA_RELEASE_PUB. The key is never fetched from the network.
 */

import { existsSync, readFileSync, realpathSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import * as p from '@clack/prompts'
import chalk from 'chalk'

import { ReleaseError, selfUpdate, type Arch, type Os } from '../utils/release.js'
import { StateError, workspaceStateDir } from '../utils/workspace-state.js'

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i !== -1 ? args[i + 1] : undefined
}

function fromFile(path: string): string | undefined {
  return existsSync(path) ? readFileSync(path, 'utf8').trim() : undefined
}

const MESSAGES: Record<string, string> = {
  bad_release_key: 'The pinned release key is not valid. The installer or your administrator provides it.',
  release_wrong_key: 'The release was signed with a different key than the one pinned on this machine. Nothing was changed.',
  release_bad_signature: 'The release signature is not valid. Nothing was changed.',
  release_invalid: 'The release document is not valid. Nothing was changed.',
  release_expired: 'The release document has expired; ask for a fresh one. Nothing was changed.',
  release_not_yet_valid: 'The release document is dated in the future; check this machine\'s clock.',
  release_rollback: 'This release is older than one already accepted on this machine. It was refused (rollback protection).',
  release_conflict: 'A different document with the same sequence number was already accepted. It was refused.',
  release_wrong_channel: 'The release is for a different channel than requested.',
  no_artifact_for_platform: 'The release has no build for this operating system / CPU.',
  artifact_mismatch: 'A download did not match the signed size or hash. Nothing was replaced.',
  update_timeout: 'The update took too long or the server did not answer; nothing was replaced. Run it again.',
  url_insecure: 'The release URL must be https:// (http:// only for localhost).',
  bad_url: 'A URL in the release setup is not valid.',
  dest_not_file: 'A file to be replaced is not a plain file; nothing was changed.',
  fs_error: 'A file could not be written completely; nothing was replaced.',
  response_too_large: 'The server sent more data than the signed release allows. Nothing was replaced.',
  locked: 'Another update or sync is already running.',
}

export async function selfUpdateCommand(args: string[]): Promise<void> {
  p.intro(chalk.bold('3pa self-update'))
  try {
    const stateDir = workspaceStateDir()
    const pub = flag(args, '--release-pub') || process.env.THREEPA_RELEASE_PUB || fromFile(join(stateDir, 'release.pub'))
    const url = flag(args, '--release-url') || process.env.THREEPA_RELEASE_URL || fromFile(join(stateDir, 'release-url'))
    if (!pub) throw new ReleaseError('bad_release_key', 'no release key')
    if (!url) throw new ReleaseError('bad_url', 'no release URL')
    const keyArg = existsSync(pub) ? readFileSync(pub, 'utf8').trim() : pub
    let libDir = flag(args, '--lib-dir')
    if (!libDir) {
      const self = realpathSync(process.argv[1] ?? '')
      if (basename(self) !== '3pa.mjs') throw new ReleaseError('bad_url', 'run this from the installed 3pa, or pass --lib-dir')
      libDir = dirname(self)
    }
    const os: Os | null = process.platform === 'linux' ? 'linux' : process.platform === 'darwin' ? 'macos' : null
    const arch: Arch | null = process.arch === 'x64' ? 'x64' : process.arch === 'arm64' ? 'arm64' : null
    if (!os || !arch) throw new ReleaseError('no_artifact_for_platform')
    const r = await selfUpdate({
      releaseUrl: url, releasePub: keyArg, channel: flag(args, '--channel'), libDir, stateDir, os, arch,
      check: args.includes('--check'),
    })
    const what = r.changed.length ? r.changed.join(', ') : 'nothing'
    p.outro(
      r.status === 'updated' ? chalk.green(`Updated to ${r.version}`) + chalk.dim(`  (${what})`)
        : r.status === 'available' ? chalk.yellow(`Update available: ${r.version}`) + chalk.dim(`  (${what})`)
        : chalk.green(`Already up to date (${r.version})`),
    )
  } catch (e) {
    const known = e instanceof ReleaseError || e instanceof StateError
    const code = known ? e.code : 'error'
    const hint = MESSAGES[code] ?? (known ? (e as Error).message : process.env.THREEPA_DEBUG ? (e as Error).message : 'Unexpected error (set THREEPA_DEBUG=1 for details).')
    p.cancel(chalk.red(hint) + chalk.dim(`  [${code}]`))
    process.exit(1)
  }
}
