# Architecture — Agentic OS layer

> Status: draft / target architecture. Decisions in [`docs/adr/`](../adr/), plan
> in [`docs/ROADMAP.md`](../ROADMAP.md).

## Purpose

Agent-owner **developer personas** work on their own machines, as if running
`opencode`, with an agent that can perform terminal and file operations — but:

- through the organisation's own **OpenAI-compatible endpoint**,
- with everything **logged tamper-evidently**,
- with policies enforced at the **gateway + audit** level,
- and with company machines protected by a **sandbox**.

The existing **web UI does not change**; it is the path for non-developer staff.

## Components

```
┌──────────────────────── MAIN SERVER (this repo) ─────────────────────┐
│ FastAPI backend                                                      │
│                                                                     │
│  api/gateway.py        OpenAI-compatible proxy  ── ADR-0004          │
│    /v1/chat/completions, /v1/embeddings, /v1/models                  │
│    persona token → company ProviderKey (base_url+key) → UPSTREAM     │
│    every call → audit;  model allowlist / quota / rate limit         │
│                                                                     │
│  services/policy_engine.py   fail-closed decision engine ── ADR-0005 │
│    execute_skill + plugin  →  allow | ask | deny                     │
│                                                                     │
│  services/audit_chain.py     hash-chained append-only  ── ADR-0006   │
│    POST /audit/ingest  (laptop → server, one-way)                    │
│                                                                     │
│  api/mcp_server.py     skills / A2A / inbox / policies → MCP  ── P2  │
│  api/well_known.py     /.well-known/opencode  signed config ─ ADR-0011│
│  services/auth (+)     short-lived per-persona token        ── ADR-0007│
│                                                                     │
│  SvelteKit web UI      UNCHANGED — non-developer staff               │
└───────▲───────────────────────────────────────────────▲─────────────┘
        │ HTTPS: /v1 + MCP + /.well-known               │ POST /audit/ingest
        │ (persona token)                               │ (append-only)
   ┌────┴──────────────────────────────────────────────┴────┐
   │  WORKSTATION  —  3pa (wrapper CLI, ADR-0009)            │
   │                                                        │
   │  3pa login   → select persona → short-lived token      │
   │  3pa run     → SANDBOX (ADR-0002):                     │
   │      • container: repo mount, egress allowlist,        │
   │        host FS / SSH / cloud creds NOT MOUNTED         │
   │      • /etc/opencode/opencode.json (baked; 3pa overrides)  │
   │      • org plugin (packages/agent-plugin):             │
   │          tool.execute.before → policy_engine           │
   │          command.executed / permission.asked → audit   │
   │      • opencode (pinned)  ── TUI, bash, edit, LSP, MCP  │
   │  heartbeat → gateway (liveness + sandbox digest)       │
   │  if gateway or audit is unreachable → opencode STOPS   │
   └────────────────────────────────────────────────────────┘
```

## Enforcement layers (ADR-0003)

| Layer | Strength | What it stops |
|-------|----------|---------------|
| LLM Gateway | **hard** (server) | Model access, quota, allowlist; offline bypass |
| Audit chain | **hard** (server) | Detection of log deletion/modification |
| Sandbox | medium | Accidental damage, injection blast radius |
| Plugin + Policy Engine (laptop) | soft | Deterrence + observability; the user can bypass |

The "policies cannot be overridden" claim is scoped to **gateway + audit**; for
developer personas the plugin-level control is soft (the developer already has a
shell). For organisations that want hard enforcement, **server-side execution**
(ADR-0002 option B) is an optional deployment model on the roadmap.

## Data flow — one tool call

1. opencode calls the model through the gateway (persona token). Gateway →
   company `ProviderKey` → the organisation's upstream. The request/response/token
   is written to the audit.
2. The model wants to call a tool (`bash`, `write`, an MCP skill…).
3. The org plugin `tool.execute.before` → gateway `/policy/decide`
   `{persona, tool, args, provenance}`. `provenance` is `untrusted` once the
   session has run a web-fetch/search tool (ADR-0010 taint tracking).
4. `policy_engine` evaluates the ordered rules → `allow | ask | deny`
   (error/timeout/unknown → `deny`). The decision is written to the audit.
5. `allow` → opencode runs the tool **inside the sandbox**. `ask` → a TUI approval
   prompt. `deny` → the plugin throws, and there is no call.
6. `command.executed` / `tool.execute.after` → audit.

## Touch points with existing code

| New | Existing code it builds on |
|-----|----------------------------|
| `api/gateway.py` | `models.ProviderKey` (+`base_url`), `core.security.decrypt`, `services/provider_service` |
| `services/policy_engine.py` | `models.Policy` / `AgentPolicyLink` / `DepartmentPolicyLink`, `agent_runtime.execute_skill` (`agent_runtime.py:334`) |
| `services/audit_chain.py` | `models.AuditLog`, `api/audit.log_action` |
| `api/mcp_server.py` | `services/mcp_client`, `services/agent_runtime.build_tool_definitions`, A2A (`api/a2a.py`) |
| persona token | `services/auth`, `models.CompanyMember` (role/scope) |
