/**
 * `3pa doctor` (ADR-0009) — check everything `3pa run` needs:
 * container runtime, login session, gateway reachability + token, the signed
 * org config, and the sandbox assets.
 */

import * as p from '@clack/prompts'
import chalk from 'chalk'
import { execa } from 'execa'

import { findSandboxDir } from '../utils/sandbox.js'
import { ensureFreshToken } from '../utils/token.js'
import { fetchAndVerifyWellKnown } from '../utils/wellknown.js'
import { loadSession } from './login.js'

type Result = { ok: boolean; label: string; detail?: string }

const ok = (label: string, detail?: string): Result => ({ ok: true, label, detail })
const bad = (label: string, detail?: string): Result => ({ ok: false, label, detail })

async function checkDocker(): Promise<Result> {
  try {
    const { stdout } = await execa('docker', ['compose', 'version', '--short'])
    return ok('container runtime', `docker compose ${stdout.trim()}`)
  } catch {
    return bad('container runtime', 'docker + `docker compose` not available')
  }
}

async function checkGateway(base: string, token: string): Promise<Result> {
  try {
    const r = await fetch(`${base}/v1/models`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(5_000),
    })
    if (r.ok) return ok('gateway + token', base)
    if (r.status === 401) return bad('gateway + token', 'token rejected — run `3pa login`')
    return bad('gateway + token', `${base} → ${r.status}`)
  } catch (e) {
    return bad('gateway + token', `${base} unreachable: ${(e as Error).message}`)
  }
}

async function checkWellKnown(base: string, pinned: string | null): Promise<Result> {
  try {
    const { keyId } = await fetchAndVerifyWellKnown(base, pinned)
    return ok('signed org config', `key ${keyId}${pinned ? '' : ' (newly pinned)'}`)
  } catch (e) {
    return bad('signed org config', (e as Error).message)
  }
}

function checkSandbox(): Result {
  try {
    return ok('sandbox assets', findSandboxDir())
  } catch (e) {
    return bad('sandbox assets', (e as Error).message)
  }
}

export async function doctor(): Promise<void> {
  p.intro(chalk.bold('3pa doctor'))

  let session = loadSession()
  const results: Result[] = [await checkDocker(), checkSandbox()]

  if (!session) {
    results.push(bad('login session', 'not logged in — run `3pa login`'))
  } else {
    session = await ensureFreshToken(session)
    const tokenAge = session.token_expires_at
      ? `access token expires ${new Date(session.token_expires_at).toLocaleTimeString()}`
      : `saved ${((Date.now() - Date.parse(session.saved_at)) / 86_400_000).toFixed(1)}d ago`
    results.push(
      ok('login session', `${session.persona_name} — ${tokenAge}`),
      await checkGateway(session.base_url, session.token),
      await checkWellKnown(session.base_url, session.wellknown_key_id ?? null),
    )
  }

  for (const r of results) {
    const icon = r.ok ? chalk.green('✓') : chalk.red('✗')
    const detail = r.detail ? chalk.dim(` — ${r.detail}`) : ''
    p.log.message(`${icon} ${r.label}${detail}`)
  }

  const failed = results.filter((r) => !r.ok).length
  if (failed) {
    p.outro(chalk.red(`${failed} check${failed > 1 ? 's' : ''} failing`))
    process.exit(1)
  }
  p.outro(chalk.green('all good — `3pa run` should work'))
}
