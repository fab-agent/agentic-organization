/**
 * agentic-organization org plugin for opencode.
 *
 * - Every tool-call lifecycle event is streamed to the backend for audit
 *   (`POST /workstation/tool-event`).
 * - `tool.execute.before` also asks the gateway `/policy/decide` (ADR-0005). When
 *   the decision is `enforced` and the effect is `deny`/`ask`, the call is
 *   aborted (opencode has no "return ask" hook, so an enforced `ask` is treated
 *   conservatively as a block with an approval message).
 * - `FABAGENT_FAIL_CLOSED=1` (ADR-0006): an unreachable audit/policy sink aborts
 *   the tool call. Default is fail-open so a developer is never blocked by an
 *   outage while the system is still being rolled out.
 *
 * Install: referenced from the managed opencode config `3pa` writes inside the
 * sandbox (ADR-0011). Env is injected by `3pa run` (ADR-0009).
 */

import { isConfigured, loadConfig } from "./config.ts";
import { PolicyClient } from "./policy.ts";
import { Reporter, type ToolEvent } from "./reporter.ts";

// Loose typing: we do not want a hard dependency on @opencode-ai/plugin's
// evolving type surface for a plugin this small.
type Hooks = Record<string, (...args: any[]) => unknown>;

export const AgentOrgPlugin = async (
  _ctx: Record<string, unknown> = {},
): Promise<Hooks> => {
  const cfg = loadConfig();
  const reporter = new Reporter(cfg);
  const policy = new PolicyClient(cfg);

  if (!isConfigured(cfg)) {
    process.stderr.write(
      "[agent-plugin] FABAGENT_BASE_URL / FABAGENT_TOKEN not set — running in no-op mode.\n",
    );
  }

  async function report(event: ToolEvent): Promise<void> {
    const outcome = await reporter.report(event);
    if (outcome === "unreachable" && cfg.failClosed) {
      throw new Error(
        "[agent-plugin] audit sink unreachable and FABAGENT_FAIL_CLOSED is set — aborting tool call.",
      );
    }
  }

  return {
    "tool.execute.before": async (input: any, _output: any) => {
      const tool = toolName(input);
      const args = input?.args ?? input?.arguments ?? null;
      const session = sessionRef(input);

      const decision = await policy.decide({
        tool,
        args: args ?? undefined,
        sessionRef: session,
      });

      if (decision === "unreachable") {
        await report({ phase: "before", tool, sessionRef: session, argsPreview: args });
        if (cfg.failClosed) {
          throw new Error(
            "[agent-plugin] policy engine unreachable and FABAGENT_FAIL_CLOSED is set — aborting tool call.",
          );
        }
        return;
      }

      await report({
        phase: "before",
        tool,
        sessionRef: session,
        argsPreview: args,
        decision: decision.effect,
      });

      if (decision.enforced && (decision.effect === "deny" || decision.effect === "ask")) {
        const verb = decision.effect === "deny" ? "denied" : "requires human approval";
        throw new Error(`[policy] ${tool} ${verb}: ${decision.reason}`);
      }
    },

    "tool.execute.after": async (input: any, output: any) => {
      await report({
        phase: "after",
        tool: toolName(input),
        sessionRef: sessionRef(input),
        resultPreview: previewOf(output),
        error: output?.error ? String(output.error) : null,
      });
    },

    "permission.asked": async (input: any, _output: any) => {
      await report({
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
