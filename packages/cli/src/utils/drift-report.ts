/**
 * The drift report (ADR-0035): what `3pa workspace status` already knows, as COUNTS, sent to the
 * platform so an operator can see it. A claim by a cooperative client, never proof (ADR-0026
 * decision 4): no file names, paths or contents leave the machine, and the platform uses it for
 * nothing but a diagnostic view.
 */

import { checkBaseUrl, scanDrift } from './provisioner.js'
import { loadState } from './workspace-state.js'

export class ReportError extends Error {
  code: string
  constructor(code: string, message?: string) {
    super(message ?? code)
    this.code = code
  }
}

export interface DriftBody {
  client_version: string
  epoch: number
  generation: number
  missing: number
  modified: number
  extra: number
  unmanaged: number
  interrupted: boolean
}

/** The counts of the last scan plus the installed record. Null when nothing is installed yet
 * (there is nothing to report on). */
export function buildReport(appHome: string, stateDir: string, clientVersion: string): DriftBody | null {
  const st = loadState(stateDir)
  if (!st?.installed) return null
  let d
  try {
    d = scanDrift(appHome)
  } catch {
    throw new ReportError('scan_failed', 'the app home could not be compared with the installed workspace')
  }
  const cap = (n: number) => Math.min(n, 100000)
  return {
    client_version: /^[0-9A-Za-z.+-]{1,32}$/.test(clientVersion) ? clientVersion : 'unknown',
    epoch: st.installed.epoch,
    generation: st.installed.generation,
    missing: cap(d.missing.length),
    modified: cap(d.modified.length),
    extra: cap(d.extraFiles.length),
    unmanaged: cap(d.unmanagedMods.length),
    interrupted: d.interrupted,
  }
}

export interface SendOptions {
  baseUrl: string
  webToken: string
  companyId?: string
  appHome: string
  stateDir: string
  clientVersion: string
  fetchImpl?: typeof fetch
}

/** 'sent', 'too_soon' (the platform allows one report per 30 seconds) or 'nothing_installed'. */
export async function sendReport(o: SendOptions): Promise<'sent' | 'too_soon' | 'nothing_installed'> {
  const base = checkBaseUrl(o.baseUrl)
  const body = buildReport(o.appHome, o.stateDir, o.clientVersion)
  if (!body) return 'nothing_installed'
  const f = o.fetchImpl ?? fetch
  const q = o.companyId ? `?company_id=${encodeURIComponent(o.companyId)}` : ''
  let res: Response
  try {
    res = await f(`${base}/me/workspace/report${q}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${o.webToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      redirect: 'error', // the token goes nowhere else
      signal: AbortSignal.timeout(20_000),
    })
  } catch (e) {
    const n = (e as Error)?.name
    throw new ReportError(n === 'TimeoutError' || n === 'AbortError' ? 'report_timeout' : 'report_failed')
  }
  if (res.status === 204) return 'sent'
  if (res.status === 429) return 'too_soon'
  throw new ReportError(`http_${res.status}`)
}
