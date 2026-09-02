import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import * as p from '@clack/prompts'
import chalk from 'chalk'

/**
 * `3pa login` (ADR-0007) — authenticate against the platform, pick an agent
 * persona, and store a short-lived persona token that `3pa run` injects into the
 * sandbox as FABAGENT_TOKEN / FABAGENT_BASE_URL.
 *
 *   3pa login                 email + password
 *   3pa login --oidc <token>  exchange an OIDC id_token from your org IdP
 *
 * Session file: ~/.config/3pa/session.json  (mode 600).
 * `THREEPA_SESSION_FILE` overrides the path (tests, CI).
 */

/** Resolved per call so `THREEPA_SESSION_FILE` / `HOME` changes take effect. */
export function sessionFile(): string {
  return (
    process.env.THREEPA_SESSION_FILE ||
    join(homedir(), '.config', '3pa', 'session.json')
  )
}

export interface Session {
  base_url: string
  token: string
  /** Persona refresh token (ADR-0007). Exchanged at /workstation/persona-token/refresh. */
  refresh_token?: string
  /** ISO time the access token expires — `3pa` refreshes ahead of this. */
  token_expires_at?: string
  persona_id: string
  persona_name: string
  persona_model?: string
  /** Ed25519 key id pinned from /.well-known/opencode/pubkey (ADR-0011 TOFU). */
  wellknown_key_id?: string
  saved_at: string
}

export function loadSession(): Session | null {
  try {
    return JSON.parse(readFileSync(sessionFile(), 'utf8')) as Session
  } catch {
    return null
  }
}

export function saveSession(s: Session): void {
  const file = sessionFile()
  mkdirSync(dirname(file), { recursive: true })
  writeFileSync(file, JSON.stringify(s, null, 2), { mode: 0o600 })
}

export function clearSession(): boolean {
  try {
    rmSync(sessionFile())
    return true
  } catch {
    return false
  }
}

async function api(base: string, path: string, init?: RequestInit): Promise<any> {
  const r = await fetch(`${base}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body?.detail || `${r.status} ${path}`)
  return body
}

export async function login(args: string[]): Promise<void> {
  p.intro(chalk.bold('3pa login'))

  const base = String(
    (await p.text({
      message: 'Platform URL',
      placeholder: 'https://agents.example.com',
      initialValue: process.env.FABAGENT_BASE_URL || '',
      validate: (v) => (v?.startsWith('http') ? undefined : 'must start with http'),
    })),
  ).replace(/\/+$/, '')
  if (p.isCancel(base)) return p.cancel('cancelled')

  // 1. Get a web session token — password or OIDC.
  let webToken: string
  const oidcIdx = args.indexOf('--oidc')
  if (oidcIdx !== -1 && args[oidcIdx + 1]) {
    const res = await api(base, '/workstation/oidc/exchange', {
      method: 'POST',
      body: JSON.stringify({ id_token: args[oidcIdx + 1] }),
    })
    webToken = res.access_token
  } else {
    const email = String(await p.text({ message: 'Email' }))
    const password = String(await p.password({ message: 'Password' }))
    if (p.isCancel(email) || p.isCancel(password)) return p.cancel('cancelled')
    const res = await api(base, '/auth/token', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    webToken = res.access_token
  }

  // 2. Pick a persona.
  const { personas } = await api(base, '/workstation/personas', {
    headers: { Authorization: `Bearer ${webToken}` },
  })
  if (!personas?.length) {
    p.cancel('You do not own or manage any agent personas.')
    return
  }
  const choice = await p.select({
    message: 'Which agent persona?',
    options: personas.map((x: any) => ({
      value: x.personnel_id,
      label: `${x.name}${x.title ? chalk.dim(` — ${x.title}`) : ''}`,
      hint: x.model,
    })),
  })
  if (p.isCancel(choice)) return p.cancel('cancelled')
  const persona = personas.find((x: any) => x.personnel_id === choice)

  // 3. Mint the persona token.
  const tok = await api(base, '/workstation/persona-token', {
    method: 'POST',
    headers: { Authorization: `Bearer ${webToken}` },
    body: JSON.stringify({ personnel_id: choice }),
  })

  saveSession({
    base_url: base,
    token: tok.token,
    refresh_token: tok.refresh_token,
    token_expires_at: tok.expires_in
      ? new Date(Date.now() + tok.expires_in * 1000).toISOString()
      : undefined,
    persona_id: persona.personnel_id,
    persona_name: persona.name,
    persona_model: persona.model,
    saved_at: new Date().toISOString(),
  })

  p.outro(
    chalk.green(`Logged in as ${chalk.bold(persona.name)}.`) +
      chalk.dim(`  (${sessionFile()})`),
  )
}
