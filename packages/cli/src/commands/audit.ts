/**
 * `3pa audit verify` (ADR-0009) — check this persona's company audit chain on
 * the server (`GET /workstation/audit/verify`, tamper-evident, ADR-0006).
 */

import * as p from '@clack/prompts'
import chalk from 'chalk'

import { api, requireSession } from '../utils/backend.js'

interface VerifyResp {
  ok: boolean
  chain_key?: string
  count?: number
  head?: string
  break_at?: number
  detail?: string
}

export async function audit(args: string[]): Promise<void> {
  const sub = args[0]
  if (sub !== 'verify') {
    p.intro(chalk.bold('3pa audit'))
    p.log.message('usage: ' + chalk.cyan('3pa audit verify'))
    p.outro('')
    process.exit(sub ? 1 : 0)
  }

  p.intro(chalk.bold('3pa audit verify'))
  const session = await requireSession()

  let resp: VerifyResp
  try {
    resp = await api<VerifyResp>(session, '/workstation/audit/verify')
  } catch (e) {
    p.cancel((e as Error).message)
    process.exit(1)
  }

  if (args.includes('--json')) {
    process.stdout.write(JSON.stringify(resp, null, 2) + '\n')
    return
  }

  if (resp.ok) {
    p.log.success(
      `chain intact — ${chalk.cyan(resp.count ?? 0)} events` +
        (resp.head ? chalk.dim(`  head ${resp.head.slice(0, 16)}…`) : ''),
    )
    p.outro(chalk.green('OK'))
  } else {
    p.log.error(
      `chain BROKEN at seq ${chalk.red(resp.break_at ?? '?')}` +
        (resp.detail ? ` — ${resp.detail}` : ''),
    )
    p.outro(chalk.red('TAMPER DETECTED'))
    process.exit(1)
  }
}
