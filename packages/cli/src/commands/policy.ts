/**
 * `3pa policy` (ADR-0009) — show the effective Policy Engine ruleset + rollout
 * mode for the logged-in persona (`GET /workstation/policy`).
 */

import * as p from '@clack/prompts'
import chalk from 'chalk'

import { api, requireSession } from '../utils/backend.js'

interface Rule {
  id?: string
  effect?: string
  reason?: string
  match?: Record<string, unknown>
}
interface PolicyResp {
  mode: string
  default_effect: string
  org_policy_count: number
  rules: Rule[]
}

export async function policy(args: string[]): Promise<void> {
  p.intro(chalk.bold('3pa policy'))
  const session = await requireSession()

  let resp: PolicyResp
  try {
    resp = await api<PolicyResp>(session, '/workstation/policy')
  } catch (e) {
    p.cancel((e as Error).message)
    process.exit(1)
  }

  if (args.includes('--json')) {
    process.stdout.write(JSON.stringify(resp, null, 2) + '\n')
    return
  }

  const modeColor =
    resp.mode === 'enforce' ? chalk.red : resp.mode === 'off' ? chalk.dim : chalk.yellow
  p.log.message(
    `mode ${modeColor(resp.mode)}  ·  default ${chalk.cyan(resp.default_effect)}  ·  ` +
      `${resp.org_policy_count} org polic${resp.org_policy_count === 1 ? 'y' : 'ies'}  ·  ` +
      `${resp.rules.length} rules`,
  )

  for (const r of resp.rules) {
    const eff =
      r.effect === 'deny'
        ? chalk.red('deny')
        : r.effect === 'ask'
          ? chalk.yellow('ask ')
          : chalk.green('allow')
    const org = r.id?.startsWith('baseline:') ? chalk.dim('[baseline]') : chalk.cyan('[org]')
    p.log.message(
      `${eff}  ${chalk.bold((r.id ?? '?').padEnd(28))} ${org} ` +
        chalk.dim(`${JSON.stringify(r.match ?? {})}`),
    )
  }

  p.outro(
    resp.mode === 'dry_run'
      ? chalk.dim('dry_run — matches are audited, not enforced')
      : resp.mode === 'enforce'
        ? chalk.red('enforce — deny/ask are applied')
        : chalk.dim('policy engine off'),
  )
}
