/**
 * `3pa refresh` (ADR-0007) — force a persona access-token refresh now. `3pa run`
 * / `3pa doctor` do this automatically near expiry; this is for scripting.
 */

import * as p from '@clack/prompts'
import chalk from 'chalk'

import { refreshNow } from '../utils/token.js'
import { loadSession } from './login.js'

export async function refresh(): Promise<void> {
  p.intro(chalk.bold('3pa refresh'))
  const session = loadSession()
  if (!session) {
    p.cancel('Not logged in. Run `3pa login` first.')
    process.exit(1)
  }
  try {
    const updated = await refreshNow(session)
    p.outro(
      chalk.green('access token refreshed') +
        (updated.token_expires_at
          ? chalk.dim(` — expires ${new Date(updated.token_expires_at).toLocaleString()}`)
          : ''),
    )
  } catch (e) {
    p.cancel((e as Error).message)
    process.exit(1)
  }
}
