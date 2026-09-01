# ADR-0007: Agent identity and short-lived credentials

- **Status:** proposed
- **Date:** 2026-09-01
- **Related:** ADR-0004, ADR-0006; block/buzz `crates/buzz-auth/`, `buzz-agent/src/auth.rs`

## Context and problem

The laptop agent needs to prove its identity to the gateway (ADR-0004) and to
audit ingest (ADR-0006). Today identity = the web session JWT
(`services/auth.py`), which is long-lived and designed for a browser. In
addition:

- Every persona/agent must be a **separate principal** (buzz: "the agent's own
  key, its own audit trail"). Blast radius = role/scope, not a prompt instruction.
- If the laptop is compromised, the damage must be bounded and revocable.

## Options considered

- **A — a long-lived API key per persona.** Simple, but valid indefinitely if it
  leaks.
- **B — a short-lived token:** `3pa login` (OIDC/SSO or platform identity) →
  a 15–60 minute persona-scoped bearer; silent refresh; a server-side revocation
  list.
- **C — mTLS / workload identity.** Strongest, heaviest to operate.

## Decision (proposed)

**B**, leaving the door open to C:

- `3pa login` → platform authentication → **persona selection** (the agents the
  user owns; `CompanyMember.role = agent_owner`, `scope_id`).
- The issued token: `sub = persona_id`, `company_id`, `scope`, a short `exp`, and
  a separate `aud` for `gateway` and `audit`.
- The token is only injected into the sandbox (ADR-0002); it is not stored in
  plaintext on the host (OS keychain / `{file:}` reference).
- **Revocation:** a server-side `revoked_jti` list; automatic revocation on loss
  of plugin heartbeat (an ADR-0003 open question).
- The agent's permissions are derived from the `CompanyMember` role/scope; which
  skill/MCP tool it can access is bounded by `AgentSkillLink` + policy.

## Direction (2026-09-01)

Platform-local identity is the **baseline** and always works (`3pa login` against
the platform, persona selection from the agents the user owns). Bringing your own
IdP is **opt-in** per organisation: `3pa login --oidc <issuer>` (or an org config
flag), where `3pa` runs a standard OIDC/device-code flow and the backend
validates the resulting assertion before minting the persona token. Orgs without
their own OAuth are never forced to set one up.

## Open questions

- OIDC claim → persona mapping (email match, or an explicit link table?).
- Which principal do unattended executions (cron flows, A2A) run as?
- Does `3pa` need device registration (device code flow) on first setup?

## Consequences

- **Positive:** A leaked token dies within minutes; per-persona revocation is
  possible; the audit binds to a clear actor identity.
- **Negative / cost:** Token refresh infrastructure, clock-skew tolerance, and an
  offline working window all need to be designed.
