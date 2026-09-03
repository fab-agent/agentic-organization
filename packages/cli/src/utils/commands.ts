/**
 * Signed command channel (ADR-0010 layer 5).
 *
 * `3pa run` polls `GET /workstation/commands` in its heartbeat loop. Each
 * command is Ed25519-signed by the backend over its canonical JSON; a command
 * whose signature does not verify against the pinned `/.well-known` key is
 * ignored (an injected prompt cannot forge it, and cannot reach this path).
 */

import * as p from '@clack/prompts'
import chalk from 'chalk'

import type { Session } from '../commands/login.js'
import { refreshNow } from './token.js'
import { verifyConfigSignature } from './wellknown.js'

interface Command {
  id: string
  persona_id: string
  kind: 'stop' | 'refresh' | 'pause' | 'resume' | 'message'
  payload: Record<string, unknown> | null
  issued_by: string
  created_at: string
}

async function ack(
  session: Session,
  id: string,
  result: string,
  fetchImpl: typeof fetch,
): Promise<void> {
  await fetchImpl(`${session.base_url}/workstation/commands/${id}/ack`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.token}`,
    },
    body: JSON.stringify({ result }),
  }).catch(() => {})
}

/**
 * Fetch pending commands, verify each, act. Returns `true` if the sandbox
 * should be stopped. `publicKeyB64` null → `--no-verify`, commands are ignored.
 */
interface Killable {
  kill: (signal?: NodeJS.Signals) => boolean
}

export async function pollCommands(
  session: Session,
  publicKeyB64: string | null,
  child: Killable,
  fetchImpl: typeof fetch = fetch,
): Promise<{ stop: boolean }> {
  let resp: Response
  try {
    resp = await fetchImpl(`${session.base_url}/workstation/commands`, {
      headers: { Authorization: `Bearer ${session.token}` },
      signal: AbortSignal.timeout(5_000),
    })
  } catch {
    return { stop: false }
  }
  if (!resp.ok) return { stop: false }
  const body = (await resp.json().catch(() => ({}))) as {
    commands?: { command: Command; signature: string }[]
  }

  let stop = false
  for (const { command, signature } of body.commands ?? []) {
    if (!publicKeyB64) {
      p.log.warn(`ignoring command ${command.kind} — --no-verify, no key to check it`)
      continue
    }
    if (!verifyConfigSignature({ config: command, signatureB64: signature, publicKeyB64 })) {
      p.log.warn(chalk.red(`ignoring command ${command.id} — bad signature`))
      continue
    }
    switch (command.kind) {
      case 'stop':
        p.log.warn(chalk.yellow(`control channel: stop (by ${command.issued_by})`))
        child.kill('SIGTERM')
        await ack(session, command.id, 'stopped', fetchImpl)
        stop = true
        break
      case 'refresh':
        try {
          await refreshNow(session, fetchImpl)
          await ack(session, command.id, 'session refreshed (applies to the next run)', fetchImpl)
        } catch (e) {
          await ack(session, command.id, `refresh failed: ${(e as Error).message}`, fetchImpl)
        }
        break
      case 'message':
        p.log.message(chalk.cyan(`● ${String(command.payload?.text ?? '')}`))
        await ack(session, command.id, 'shown', fetchImpl)
        break
      default:
        await ack(session, command.id, `${command.kind} not supported by opencode; ignored`, fetchImpl)
    }
  }
  return { stop }
}
