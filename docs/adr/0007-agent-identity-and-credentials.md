# ADR-0007: Agent identity and short-lived credentials

- **Status:** accepted (platform-local identity + refresh + revocation done; device registration pending)
- **Date:** 2026-09-01 (accepted 2026-09-02)
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

## Implementation status (2026-09-02)

- `GET /workstation/personas` — the agent personas a user may act as
  (founder/executive → all company agents; otherwise agents they are the
  responsible human for, or `agent_owner` for).
- `POST /workstation/persona-token` — owner-scoped mint (replaces the
  manager-only `/gateway/persona-token` for the login flow); issues a
  short-lived token, `aud` = gateway + audit.
- `POST /workstation/oidc/exchange` (`services/oidc.py`) — verifies an OIDC ID
  token (JWKS, iss/aud/exp) against `AppConfig` `oidc.*`; maps the `email` claim
  to an existing `User` and returns a normal web session token. **No
  auto-provisioning.** Off unless `oidc.enabled = true`.
- `3pa login` (`packages/cli`) — password or `--oidc <id_token>` → pick persona →
  store `~/.config/3pa/session.json` (0600); `sandbox/run.sh` reads it.

### Token refresh + revocation (2026-09-02)

- **Two token types** (`services/gateway_auth.py`): an **access** token
  (`typ=persona`, `aud=[gateway,audit]`, `PERSONA_TOKEN_TTL_MINUTES`, default 60)
  and a **refresh** token (`typ=persona_refresh`, `aud=refresh`,
  `PERSONA_REFRESH_TTL_HOURS`, default 12). Every token carries a `jti`.
- `POST /workstation/persona-token` now returns `{token, refresh_token,
  expires_in}`.
- `POST /workstation/persona-token/refresh` — refresh token → fresh pair; the
  presented refresh token is **rotated** (old `jti` blacklisted, cannot replay).
- `POST /workstation/persona-token/revoke` — kills every token for a persona (the
  "laptop lost" button). Auth: the persona's platform owner **or** a still-valid
  token for that same persona (self-revoke, `3pa logout --revoke`).
- **Revocation** (`services/persona_revocation.py`, checked in `api/deps.py`,
  fail-closed): per-`jti` blacklist (`RevokedToken`) + a per-persona `not_before`
  marker (`PersonaTokenState`) that kills everything issued earlier without
  needing the jti. Migration `b7d1e93a4c25`.
- `3pa`: `login` stores the refresh token + expiry; `run` / `doctor` call
  `ensureFreshToken` (refresh within 2 min of expiry) and `run` retries once via
  refresh on a 401; `3pa refresh` forces it; `3pa logout [--revoke]`.
- The heartbeat now probes the **unauthenticated** `/health` for liveness, not
  `/v1/models` — see the open item below.

- **Auto-revoke + prune** (`services/persona_revocation.revocation_maintenance`,
  scheduled every 5 min): prunes `RevokedToken` rows older than 24 h (their
  tokens have expired); and — opt-in via `AppConfig heartbeat.autorevoke=true`,
  threshold `heartbeat.stale_minutes` (default 10) — `revoke_all()` any persona
  whose `PersonaHeartbeat` (ADR-0009) has gone stale, i.e. `3pa run` died with a
  token still live.

Still open: device registration.

## Open questions

- OIDC claim → persona mapping when one email owns several personas (today: the
  user still picks in `3pa login`).
- Which principal do unattended executions (cron flows, A2A) run as?
- Does `3pa` need device registration (device code flow) on first setup?
- **In-sandbox token rotation.** The access token is injected into the container
  env at launch, so a session longer than the access TTL (60 min) outlives its
  token — the plugin's gateway calls start 401ing. Fix options: `3pa` writes a
  rotating token to a file the container reads; or the plugin refreshes itself.
  Until then a long run is bounded by `PERSONA_TOKEN_TTL_MINUTES`.

## Consequences

- **Positive:** A leaked token dies within minutes; per-persona revocation is
  possible; the audit binds to a clear actor identity.
- **Negative / cost:** Token refresh infrastructure, clock-skew tolerance, and an
  offline working window all need to be designed. The refresh + revocation tables
  grow unbounded — a periodic prune of expired `RevokedToken` rows is a follow-up.
