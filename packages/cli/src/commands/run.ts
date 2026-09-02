/**
 * `3pa run [project]` (ADR-0009) — launch opencode inside the managed sandbox.
 *
 *   1. preflight: the gateway is reachable and the persona token is valid
 *      (fail-closed — we do not start if it is not)
 *   2. preflight: fetch + Ed25519-verify the org config at /.well-known/opencode
 *      (ADR-0011); pin the signing key on first use, refuse a silent rotation
 *   3. bring up `sandbox/compose.yaml` — the sandbox on an internal-only network
 *      behind the egress proxy (ADR-0002 / ADR-0010) — with the token and model
 *      injected only into the container environment
 *   4. while it runs, heartbeat the gateway; warn (and, when the org is in
 *      enforce mode, stop the sandbox) if it goes unreachable
 *
 * Flags: --model <m>  --allow <hosts>  --no-egress  --no-verify
 *        --accept-key-change  --no-build
 */

import { resolve } from 'node:path'
import * as p from '@clack/prompts'
import chalk from 'chalk'
import { execa, type ExecaError } from 'execa'

import { findSandboxDir } from '../utils/sandbox.js'
import { ensureFreshToken, refreshNow } from '../utils/token.js'
import { fetchAndVerifyWellKnown } from '../utils/wellknown.js'
import { loadSession, saveSession, sessionFile } from './login.js'

interface RunOpts {
  projectDir: string
  model?: string
  allow?: string
  egress: boolean
  verify: boolean
  acceptKeyChange: boolean
  build: boolean
}

export function parseRunArgs(args: string[]): RunOpts {
  const opts: RunOpts = {
    projectDir: process.cwd(),
    egress: true,
    verify: true,
    acceptKeyChange: false,
    build: true,
  }
  const positional: string[] = []
  for (let i = 0; i < args.length; i++) {
    const a = args[i]
    if (a === '--no-egress') opts.egress = false
    else if (a === '--no-verify') opts.verify = false
    else if (a === '--accept-key-change') opts.acceptKeyChange = true
    else if (a === '--no-build') opts.build = false
    else if (a === '--model') opts.model = args[++i]
    else if (a === '--allow') opts.allow = args[++i]
    else if (a.startsWith('--')) throw new Error(`unknown flag: ${a}`)
    else positional.push(a)
  }
  if (positional[0]) opts.projectDir = resolve(positional[0])
  return opts
}

/** Authenticated — does the persona token still work on the gateway. */
async function tokenValid(base: string, token: string): Promise<boolean> {
  try {
    const r = await fetch(`${base}/v1/models`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(5_000),
    })
    return r.ok
  } catch {
    return false
  }
}

/** Unauthenticated liveness — is the gateway reachable at all (heartbeat). */
async function gatewayHealthy(base: string): Promise<boolean> {
  try {
    const r = await fetch(`${base}/health`, { signal: AbortSignal.timeout(5_000) })
    return r.ok
  } catch {
    return false
  }
}

function mergeAllow(existing: string | undefined, extra: string): string {
  return [existing, extra].filter(Boolean).join(',')
}

export async function run(args: string[]): Promise<void> {
  p.intro(chalk.bold('3pa run'))

  let opts: RunOpts
  try {
    opts = parseRunArgs(args)
  } catch (e) {
    p.cancel((e as Error).message)
    process.exit(2)
  }

  let session = loadSession()
  if (!session) {
    p.cancel('Not logged in. Run `3pa login` first.')
    process.exit(1)
  }

  const spin = p.spinner()

  // 1. Gateway + token — refresh ahead of expiry, and once more on a 401.
  spin.start('Checking the gateway and persona token')
  if (!(await gatewayHealthy(session.base_url))) {
    spin.stop(chalk.red(`gateway unreachable — ${session.base_url}`))
    process.exit(1)
  }
  session = await ensureFreshToken(session)
  if (!(await tokenValid(session.base_url, session.token))) {
    try {
      session = await refreshNow(session)
    } catch {
      spin.stop(chalk.red('persona token invalid'))
      p.log.info(`re-run \`3pa login\` — token: ${chalk.dim(sessionFile())}`)
      process.exit(1)
    }
    if (!(await tokenValid(session.base_url, session.token))) {
      spin.stop(chalk.red('persona token invalid even after refresh — run `3pa login`'))
      process.exit(1)
    }
  }
  spin.stop(chalk.green('gateway and token OK'))

  // 2. Signed org config (ADR-0011).
  let failClosed = false
  let policyMode = 'unknown'
  if (opts.verify) {
    spin.start('Verifying the signed org config')
    try {
      const { bundle, keyId } = await fetchAndVerifyWellKnown(
        session.base_url,
        session.wellknown_key_id ?? null,
        { allowKeyChange: opts.acceptKeyChange },
      )
      const x = ((bundle.config as Record<string, unknown>)?.['x-fabagent'] ??
        {}) as Record<string, unknown>
      failClosed = Boolean(x.fail_closed)
      policyMode = String(x.policy_mode ?? 'unknown')
      if (keyId !== session.wellknown_key_id) {
        saveSession({ ...session, wellknown_key_id: keyId })
        p.log.info(`pinned signing key ${chalk.cyan(keyId)}`)
      }
      spin.stop(chalk.green(`org config verified — policy mode: ${policyMode}`))
    } catch (e) {
      spin.stop(chalk.red(`org config: ${(e as Error).message}`))
      process.exit(1)
    }
  } else {
    p.log.warn('signature verification skipped (--no-verify)')
  }

  // 3. Launch.
  const model = opts.model ?? session.persona_model ?? 'fabagent/qwen-turbo'
  const sandboxDir = findSandboxDir()
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    FABAGENT_BASE_URL: session.base_url,
    FABAGENT_TOKEN: session.token,
    FABAGENT_MODEL: model,
    PROJECT_DIR: opts.projectDir,
  }
  if (opts.allow) env.EGRESS_ALLOWLIST = mergeAllow(process.env.EGRESS_ALLOWLIST, opts.allow)
  if (failClosed) env.FABAGENT_FAIL_CLOSED = '1'

  p.log.info(
    `persona ${chalk.bold(session.persona_name)} · model ${chalk.cyan(model)} · ` +
      `project ${chalk.cyan(opts.projectDir)}`,
  )

  const composeFile = resolve(sandboxDir, 'compose.yaml')
  let child: ReturnType<typeof execa>
  if (!opts.egress) {
    p.log.warn('egress proxy OFF (--no-egress) — the sandbox has unrestricted network')
    child = execa('bash', [resolve(sandboxDir, 'run.sh'), opts.projectDir], {
      stdio: 'inherit',
      env,
    })
  } else {
    const composeArgs = ['compose', '-f', composeFile, 'run', '--rm']
    if (opts.build) composeArgs.push('--build')
    composeArgs.push('sandbox')
    child = execa('docker', composeArgs, { stdio: 'inherit', env })
  }

  // 4. Heartbeat while the sandbox runs (liveness only — the in-container token
  //    cannot be rotated after launch, so a long session is bounded by its TTL).
  const heartbeat = startHeartbeat(session.base_url, failClosed, child)

  const cleanup = async (): Promise<void> => {
    clearInterval(heartbeat)
    if (opts.egress) {
      // Tear down the lingering `egress` service.
      await execa('docker', ['compose', '-f', composeFile, 'down'], {
        env,
        stdio: 'ignore',
      }).catch(() => {})
    }
  }

  try {
    await child
  } catch (e) {
    const err = e as ExecaError
    await cleanup()
    // A clean Ctrl-C / opencode exit is not an error worth a stack trace.
    process.exit(typeof err.exitCode === 'number' ? err.exitCode : 1)
  }
  await cleanup()
  p.outro(chalk.dim('sandbox exited'))
}

function startHeartbeat(
  base: string,
  failClosed: boolean,
  child: ReturnType<typeof execa>,
): NodeJS.Timeout {
  let misses = 0
  const timer = setInterval(async () => {
    if (await gatewayHealthy(base)) {
      misses = 0
      return
    }
    misses += 1
    if (misses === 2) {
      p.log.warn(chalk.yellow('gateway heartbeat failing — audit/policy may not be recording'))
    }
    if (misses >= 4 && failClosed) {
      p.log.error(chalk.red('gateway unreachable in enforce mode — stopping the sandbox (fail-closed)'))
      child.kill('SIGTERM')
      clearInterval(timer)
    }
  }, 30_000)
  timer.unref()
  return timer
}
