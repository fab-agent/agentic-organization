/**
 * `3pa stop` (ADR-0010 layer 5) — queue a signed `stop` command for the
 * logged-in persona's running `3pa run` session (from another terminal).
 * `3pa msg "<text>"` / `3pa signal <kind>` cover the other command kinds.
 */

import * as p from '@clack/prompts'
import chalk from 'chalk'

import { api, requireSession } from '../utils/backend.js'

const KINDS = new Set(['stop', 'refresh', 'pause', 'resume', 'message'])

export async function signal(args: string[]): Promise<void> {
  const kind = args[0] === undefined ? 'stop' : args[0]
  const text = args.slice(1).join(' ')

  p.intro(chalk.bold(`3pa ${kind === 'stop' ? 'stop' : `signal ${kind}`}`))
  if (!KINDS.has(kind)) {
    p.cancel(`kind must be one of: ${[...KINDS].join(', ')}`)
    process.exit(2)
  }
  const session = await requireSession()

  try {
    const res = await api<{ id: string; kind: string }>(session, '/workstation/commands', {
      method: 'POST',
      body: JSON.stringify({
        personnel_id: session.persona_id,
        kind,
        payload: kind === 'message' && text ? { text } : undefined,
      }),
    })
    p.outro(
      chalk.green(`queued ${res.kind}`) +
        chalk.dim(`  (${res.id.slice(0, 8)}) — the running session picks it up within ~30s`),
    )
  } catch (e) {
    p.cancel((e as Error).message)
    process.exit(1)
  }
}
