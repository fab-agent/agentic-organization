/**
 * agentic-organization org plugin for opencode.
 *
 * Phase 0 (this version): observe only. Every tool-call lifecycle event is
 * streamed to the backend for audit (`POST /workstation/tool-event`). Nothing is
 * blocked.
 *
 * Phase 1 (ADR-0005): `tool.execute.before` additionally calls the gateway's
 * `/policy/decide`; a `deny` throws to abort the tool call, an `ask` maps to an
 * opencode approval prompt. `FABAGENT_FAIL_CLOSED=1` makes an unreachable
 * audit/policy sink abort execution (ADR-0006).
 *
 * Install: referenced from the managed opencode config `3pa` writes inside the
 * sandbox (ADR-0011). Env (`FABAGENT_BASE_URL`, `FABAGENT_TOKEN`, …) is injected
 * by `3pa run` (ADR-0009).
 */

import { isConfigured, loadConfig } from "./config.ts";
import { Reporter, type ToolEvent } from "./reporter.ts";

// Loose typing: we do not want a hard dependency on @opencode-ai/plugin's
// evolving type surface for a plugin this small.
type Hooks = Record<string, (...args: any[]) => unknown>;

export const AgentOrgPlugin = async (_ctx: Record<string, unknown> = {}): Promise<Hooks> => {
  const cfg = loadConfig();
  const reporter = new Reporter(cfg);

  if (!isConfigured(cfg)) {
    process.stderr.write(
      "[agent-plugin] FABAGENT_BASE_URL / FABAGENT_TOKEN not set — running in no-op mode.\n",
    );
  }

  async function handle(event: ToolEvent): Promise<void> {
    const outcome = await reporter.report(event);
    if (outcome === "unreachable" && cfg.failClosed) {
      // Phase 1 (ADR-0006): no audit sink → no execution.
      throw new Error(
        "[agent-plugin] audit sink unreachable and FABAGENT_FAIL_CLOSED is set — aborting tool call.",
      );
    }
  }

  return {
    "tool.execute.before": async (input: any, _output: any) => {
      await handle({
        phase: "before",
        tool: toolName(input),
        sessionRef: sessionRef(input),
        argsPreview: input?.args ?? input?.arguments ?? null,
      });
      // TODO(ADR-0005): call gateway /policy/decide; throw on "deny".
    },

    "tool.execute.after": async (input: any, output: any) => {
      await handle({
        phase: "after",
        tool: toolName(input),
        sessionRef: sessionRef(input),
        resultPreview: previewOf(output),
        error: output?.error ? String(output.error) : null,
      });
    },

    "permission.asked": async (input: any, _output: any) => {
      await handle({
        phase: "permission_asked",
        tool: toolName(input),
        sessionRef: sessionRef(input),
        argsPreview: input?.args ?? null,
      });
    },
  };
};

function toolName(input: any): string {
  return input?.tool ?? input?.name ?? input?.toolName ?? "unknown";
}

function sessionRef(input: any): string | null {
  return input?.sessionID ?? input?.sessionId ?? input?.session?.id ?? null;
}

function previewOf(output: any): string | null {
  if (output == null) return null;
  if (typeof output === "string") return output.slice(0, 2000);
  const candidate = output.output ?? output.result ?? output.content ?? output;
  try {
    return JSON.stringify(candidate).slice(0, 2000);
  } catch {
    return String(candidate).slice(0, 2000);
  }
}

export default AgentOrgPlugin;
