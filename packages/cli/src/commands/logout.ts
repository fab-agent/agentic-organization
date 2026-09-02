/**
 * `3pa logout` (ADR-0007) — drop the local session. With `--revoke` it also
 * calls `/workstation/persona-token/revoke`, killing every token for this
 * persona server-side (use it if the laptop may be compromised).
 */

import * as p from '@clack/prompts'
import chalk from 'chalk'

import { clearSession, loadSession } from './login.js'

export async function logout(args: string[]): Promise<void> {
  p.intro(chalk.bold('3pa logout'))
  const session = loadSession()
  if (!session) {
    p.outro(chalk.dim('no active session'))
    return
  }

  if (args.includes('--revoke')) {
    try {
      const r = await fetch(`${session.base_url}/workstation/persona-token/revoke`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session.token}`,
        },
        body: JSON.stringify({ personnel_id: session.persona_id }),
      })
      // 403: an access token cannot self-revoke; the persona owner must do it
      // from the platform. Still drop the local session below.
      p.log[r.ok ? 'success' : 'warn'](
        r.ok
          ? 'server-side tokens revoked'
          : `server-side revoke not accepted (${r.status}) — revoke from the platform`,
      )
    } catch (e) {
      p.log.warn(`server-side revoke failed: ${(e as Error).message}`)
    }
  }

  clearSession()
  p.outro(chalk.green(`logged out ${chalk.dim(`(${session.persona_name})`)}`))
}
