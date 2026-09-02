import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
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
 * Session file: ~/.config/3pa/session.json  (mode 600)
 */

const SESSION_DIR = join(homedir(), '.config', '3pa')
const SESSION_FILE = join(SESSION_DIR, 'session.json')

export interface Session {
  base_url: string
  token: string
  persona_id: string
  persona_name: string
  saved_at: string
}

export function loadSession(): Session | null {
  try {
    return JSON.parse(readFileSync(SESSION_FILE, 'utf8')) as Session
  } catch {
    return null
  }
}

function saveSession(s: Session): void {
  mkdirSync(SESSION_DIR, { recursive: true })
  writeFileSync(SESSION_FILE, JSON.stringify(s, null, 2), { mode: 0o600 })
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
    persona_id: persona.personnel_id,
    persona_name: persona.name,
    saved_at: new Date().toISOString(),
  })

  p.outro(
    chalk.green(`Logged in as ${chalk.bold(persona.name)}.`) +
      chalk.dim(`  (${SESSION_FILE})`),
  )
}
