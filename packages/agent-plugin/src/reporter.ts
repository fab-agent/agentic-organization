/**
 * Reporter — posts tool-call lifecycle events to the backend
 * (`POST /workstation/tool-event`, ADR-0001 / ADR-0006).
 *
 * Phase 0: audit only. `report()` never returns a decision; it resolves to
 * `"ok"` or `"unreachable"`. The caller decides what to do with `"unreachable"`
 * based on `failClosed`.
 */

import type { PluginConfig } from "./config.ts";

export type ToolPhase = "before" | "after" | "permission_asked";

export interface ToolEvent {
  phase: ToolPhase;
  tool: string;
  sessionRef?: string | null;
  argsPreview?: unknown;
  resultPreview?: string | null;
  /** Set from Phase 1 once the policy engine returns a decision (ADR-0005). */
  decision?: "allow" | "ask" | "deny" | null;
  error?: string | null;
}

export type ReportOutcome = "ok" | "unreachable" | "skipped";

type FetchFn = typeof fetch;

export class Reporter {
  private readonly cfg: PluginConfig;
  private readonly fetchImpl: FetchFn;

  constructor(cfg: PluginConfig, fetchImpl: FetchFn = fetch) {
    this.cfg = cfg;
    this.fetchImpl = fetchImpl;
  }

  async report(event: ToolEvent): Promise<ReportOutcome> {
    if (!this.cfg.baseUrl || !this.cfg.token) {
      if (this.cfg.debug) {
        process.stderr.write(
          "[agent-plugin] not configured (FABAGENT_BASE_URL / FABAGENT_TOKEN) — skipping report\n",
        );
      }
      return "skipped";
    }

    const payload = {
      phase: event.phase,
      tool: event.tool,
      session_ref: event.sessionRef ?? null,
      args_preview: normalisePreview(event.argsPreview),
      result_preview: event.resultPreview ?? null,
      decision: event.decision ?? null,
      error: event.error ?? null,
      client_ts: new Date().toISOString(),
    };

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.cfg.timeoutMs);
    try {
      const resp = await this.fetchImpl(
        `${this.cfg.baseUrl}/workstation/tool-event`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${this.cfg.token}`,
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        },
      );
      if (this.cfg.debug) {
        process.stderr.write(
          `[agent-plugin] ${event.phase} ${event.tool} -> ${resp.status}\n`,
        );
      }
      return resp.ok ? "ok" : "unreachable";
    } catch (err) {
      if (this.cfg.debug) {
        process.stderr.write(
          `[agent-plugin] report failed: ${(err as Error).message}\n`,
        );
      }
      return "unreachable";
    } finally {
      clearTimeout(timer);
    }
  }
}

function normalisePreview(value: unknown): unknown {
  if (value == null) return null;
  if (typeof value === "string") return value.slice(0, 2000);
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return String(value).slice(0, 2000);
  }
}
