---
sidebar_position: 1
---

# Developer Workstation: Overview

:::tip In short
Developers work on their own computers with **opencode**, but model calls, commands and actions **go through the company server**: keys are not kept on the workstation, every command is evaluated against rules, and everything is written to a tamper-evident record. This section is for technical teams; business users should see the [User Guide](/guide/onboarding).
:::

The platform's web interface is used to **define** agents: who is in which department, which model, which skills, which policies. The **Developer Workstation** layer (code name *Agentic OS*) lets developer personas do real work with these definitions: on their own workstation, inside the code base.

A developer persona runs [**opencode**](https://opencode.ai) on the workstation. All model traffic goes through a central **gateway**, every tool call is evaluated with **executable policies**, and every action is written to a **tamper-evident audit chain**. The web interface is unaware of this layer; the layer is optional and works alongside it.

---

## Why

| Problem | The layer's answer |
|---|---|
| Agents see raw API keys | The gateway: they connect with a persona token, the upstream key is never seen |
| No proof for "what did the agent do?" | Hash-chained audit + external anchoring |
| Policies are only suggestions in the system prompt | A fail-closed policy engine that runs before the tool call |
| A local agent can run unlimited commands | A mandatory local sandbox + egress allowlist |
| Tool misuse through prompt injection | Layered injection defense (provenance tracking → egress → signed command channel) |
| Leak of long-lived credentials | ~60-minute access token + revocation + automatic stale-session cleanup |

---

## Components

```
  ┌─────────────────────── Workstation ────────────────────────┐
  │                                                            │
  │   3pa CLI ──► opencode  (managed sandbox container)        │
  │                │  ▲         │                               │
  │        plugin  │  │ base-prompt.md (guardrail)             │
  │                ▼  │         ▼                               │
  │        egress proxy (allowlist)  ──────────────────────┐    │
  └───────────────────────────────────────────────────────│────┘
                                                          │
                       HTTPS (persona bearer token)       │
                                                          ▼
  ┌──────────────────────── Platform backend ──────────────────┐
  │                                                            │
  │   /v1/*          LLM Gateway ──► the company's upstream    │
  │   /policy/decide Policy Engine (off|dry_run|enforce)       │
  │   /workstation/* heartbeat · token · signed command channel│
  │   /audit/*       Audit Chain ──► S3 Object Lock anchor     │
  │   /.well-known/opencode   signed managed configuration     │
  │   /mcp           persona skills (JSON-RPC)                 │
  └────────────────────────────────────────────────────────────┘
```

| Component | Document |
|---|---|
| Central LLM Gateway | [llm-gateway](./llm-gateway.md) |
| Executable Policy Engine | [policy-engine](./policy-engine.md) |
| Tamper-evident Audit Chain | [audit-chain](./audit-chain.md) |
| Persona Identity and Tokens | [identity](./identity.md) |
| The `3pa` Workstation CLI | [cli](./cli.md) |
| Isolated Execution Environment (sandbox) | [sandbox](./sandbox.md) |
| Prompt Injection Defense | [injection-defense](./injection-defense.md) |
| Managed opencode Configuration | [managed-config](./managed-config.md) |

---

## Design principles

- **Fail-closed.** Policy evaluation, token validation and the revocation check: on error they all block, they do not let through.
- **Defaults are permissive.** Gateway quotas, the policy mode (`dry_run`), severity scoring: none restricts until explicitly configured. The layer is first observed, then enforced.
- **The web interface is untouched.** The execution layer has its own routers, its own tables and its own CI workflows.
- **Decision = code.** Every architecture decision is an ADR under `docs/adr/` (ADR-0001 … ADR-0013).
