/**
 * Persona access-token freshness (ADR-0007).
 *
 * The access token is short-lived; `3pa` holds a longer-lived refresh token and
 * exchanges it at `/workstation/persona-token/refresh` (which rotates it). Call
 * `ensureFreshToken` before using `session.token`: it refreshes when the token
 * is expired / within the skew window, persists the new pair, and returns the
 * updated session. On failure it returns the session unchanged so the caller can
 * still try the old token (and surface a clean "run `3pa login`").
 */

import { type Session, saveSession } from '../commands/login.js'

const SKEW_MS = 120_000 // refresh if it expires within 2 minutes

export function isExpiring(session: Session, now = Date.now()): boolean {
  if (!session.token_expires_at) return false
  return Date.parse(session.token_expires_at) - now <= SKEW_MS
}

export async function refreshNow(
  session: Session,
  fetchImpl: typeof fetch = fetch,
): Promise<Session> {
  if (!session.refresh_token) throw new Error('no refresh token — run `3pa login`')
  const r = await fetchImpl(`${session.base_url}/workstation/persona-token/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: session.refresh_token }),
  })
  if (!r.ok) throw new Error(`refresh failed (${r.status}) — run \`3pa login\``)
  const body = (await r.json()) as {
    token: string
    refresh_token: string
    expires_in?: number
  }
  const updated: Session = {
    ...session,
    token: body.token,
    refresh_token: body.refresh_token,
    token_expires_at: body.expires_in
      ? new Date(Date.now() + body.expires_in * 1000).toISOString()
      : undefined,
    saved_at: new Date().toISOString(),
  }
  saveSession(updated)
  return updated
}

/** Refresh proactively when the token is near expiry; otherwise return as-is. */
export async function ensureFreshToken(
  session: Session,
  fetchImpl: typeof fetch = fetch,
): Promise<Session> {
  if (!isExpiring(session) || !session.refresh_token) return session
  try {
    return await refreshNow(session, fetchImpl)
  } catch {
    return session
  }
}
