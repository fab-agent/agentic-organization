/**
 * Small authenticated GET/POST helper against the backend, using the persona
 * token from the session (ADR-0009 subcommands).
 */

import { ensureFreshToken } from './token.js'
import { loadSession, type Session } from '../commands/login.js'

export async function requireSession(): Promise<Session> {
  const s = loadSession()
  if (!s) {
    process.stderr.write('Not logged in. Run `3pa login` first.\n')
    process.exit(1)
  }
  return ensureFreshToken(s)
}

export async function api<T = unknown>(
  session: Session,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const r = await fetch(`${session.base_url}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.token}`,
      ...(init.headers ?? {}),
    },
    signal: AbortSignal.timeout(10_000),
  })
  const body = (await r.json().catch(() => ({}))) as any
  if (!r.ok) throw new Error(body?.detail || `${r.status} ${path}`)
  return body as T
}
