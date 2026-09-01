/**
 * PolicyClient — asks the gateway `/policy/decide` whether a tool call is
 * allowed (ADR-0005). Phase 1.
 *
 * `decide()` resolves to a PolicyDecision, or `"unreachable"` when the engine
 * cannot be reached. The caller combines `"unreachable"` with `failClosed` to
 * decide whether to abort.
 */

import type { PluginConfig } from "./config.ts";

export interface PolicyQuery {
  tool: string;
  args?: Record<string, unknown>;
  provenance?: "trusted" | "untrusted";
  sessionRef?: string | null;
}

export interface PolicyDecision {
  effect: "allow" | "ask" | "deny";
  reason: string;
  matched_rule: string | null;
  mode: string;
  /** True → the caller must actually block/prompt. */
  enforced: boolean;
  /** True → verdict came from a fail-closed path (broken policy config). */
  fail_closed?: boolean;
}

type FetchFn = typeof fetch;

export class PolicyClient {
  private readonly cfg: PluginConfig;
  private readonly fetchImpl: FetchFn;

  constructor(cfg: PluginConfig, fetchImpl: FetchFn = fetch) {
    this.cfg = cfg;
    this.fetchImpl = fetchImpl;
  }

  async decide(query: PolicyQuery): Promise<PolicyDecision | "unreachable"> {
    if (!this.cfg.baseUrl || !this.cfg.token) return "unreachable";

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.cfg.timeoutMs);
    try {
      const resp = await this.fetchImpl(`${this.cfg.baseUrl}/policy/decide`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.cfg.token}`,
        },
        body: JSON.stringify({
          tool: query.tool,
          args: query.args ?? {},
          provenance: query.provenance ?? "trusted",
          session_ref: query.sessionRef ?? null,
        }),
        signal: controller.signal,
      });
      if (!resp.ok) return "unreachable";
      return (await resp.json()) as PolicyDecision;
    } catch {
      return "unreachable";
    } finally {
      clearTimeout(timer);
    }
  }
}
