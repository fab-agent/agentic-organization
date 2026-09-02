# ADR-0001: Adopt opencode as the developer workstation client

- **Status:** accepted
- **Date:** 2026-09-01
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0002, ADR-0004, ADR-0008, ADR-0009

## Context and problem

Today the platform runs agents through the web (SvelteKit UI → FastAPI → SSE
chat). The next goal: **agent-owner developer personas working on their own
machines** with an agent that can perform terminal/file operations — "as if they
had installed `opencode` on their own machine". At the same time:

- The web version **must stay unchanged** (it is the path for non-developer staff).
- The organisation wants to route LLM traffic through its own OpenAI-compatible
  endpoint (ADR-0004).
- Everything must be logged, and policies must not be overridable (ADR-0003, ADR-0006).

Question: how do we build the laptop agent?

## Options considered

- **A — adopt opencode as the client.** Use `anomalyco/opencode` (formerly
  `sst/opencode`) as-is; pin the gateway via managed config, report/gate every
  tool call to the backend via a plugin, and connect the backend as an MCP server
  (skills / A2A / inbox / policies).
  - `+` Battle-tested agent loop, TUI, LSP, MCP, and plugin system already exist.
  - `+` Fastest path; maintenance burden sits with the opencode community.
  - `+` BYO endpoint is already solved via `provider.baseURL` + `@ai-sdk/openai-compatible`.
  - `−` Dependency on opencode and the Bun runtime.
  - `−` opencode has managed-config bypass gaps (see ADR-0003).
- **B — build our own TUI + executor** (opentui / Ink / Bubble Tea) and connect it
  to the existing FastAPI SSE.
  - `+` Full control, our own brand, policy baked into the agent core.
  - `−` Agent loop, tool execution, file diff, LSP, approval UX from scratch. Months.
- **C — hybrid:** core agent logic in the backend (`agent_runtime`), a thin TUI +
  local executor on the laptop; the executor routes every command through a
  backend broker.
  - `+` Enforcement in the backend.
  - `−` Local executor protocol + latency; still a significant amount of new code.

## Decision

**Short/medium term: A.** We adopt opencode as the developer workstation client.
Integration through three surfaces:

1. **Managed config** (`/etc/opencode/…`, root-owned) — pins the LLM gateway
   (ADR-0004), disables unapproved providers, disables `/share`.
2. **Org plugin** — `tool.execute.before` → Policy Engine (ADR-0005) query;
   `command.executed` / `permission.asked` → audit stream (ADR-0006).
3. **Backend MCP server** — `skills`, `delegate_to_agent` (A2A), `inbox`,
   `journal`, `policies` exposed to opencode as tools.

B (our own TUI) is **deferred in ADR-0008**; if needed it is added as a separate
client with Bubble Tea. C will be revisited in a future ADR if enforcement needs
to be hardened.

## Consequences

- **Positive:** An end-to-end working developer experience within weeks. The web
  version is untouched.
- **Negative / cost:** Dependency on opencode + Bun. The burden of tracking
  opencode's breaking changes. The plugin/MCP API must be pinned to the opencode
  version.
- **Accepted residual risk:** opencode runs on the user's machine, with the
  user's privileges — plugin-based policy is a soft control (ADR-0003).
- **Follow-ups:** ADR-0009 (`3pa` wrapper), ADR-0011 (managed config), the
  `agent-plugin.yml` and `gateway.yml` CI jobs for the plugin + MCP server.
