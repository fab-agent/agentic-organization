# Roadmap — Agentic OS layer

This document is the phased plan for moving the platform from **web-first agent
management** to a system where developers work on their own machines with a
sandboxed agent (opencode), all traffic goes through a central gateway, and
everything is logged tamper-evidently.

Full rationale for the decisions: [`docs/adr/`](adr/). Architecture picture:
[`docs/architecture/agentic-os.md`](architecture/agentic-os.md).

## Fixed principles

- **The web version stays unchanged.** The new execution model is optional;
  non-developer staff continue on the web.
- **opencode is adopted, not forked** (ADR-0001). Integration: managed config +
  org plugin + backend MCP server.
- **Execution on the laptop, inside a sandbox** (ADR-0002).
- **Hard enforcement = gateway + audit** (server side). Plugin-level policy is a
  soft control (ADR-0003).
- Development proceeds via ADRs + path-scoped GitHub Actions.

---

## Phase 0 — PoC (one persona, end to end)

**Goal:** a developer works as a persona with opencode on their laptop; model
traffic goes through the backend gateway; every tool call is written to the audit
(without blocking yet).

- [x] `docs/adr/` + ADR-0001/0002/0004/0008 (accepted), the rest proposed.
- [x] `backend/api/gateway.py` — `POST /v1/chat/completions` passthrough (stream +
      non-stream): persona token → the company's `ProviderKey` (base_url + key) →
      upstream; model + token + latency + prompt hash to `AuditLog`. `GET /v1/models`.
      `POST /gateway/persona-token` (manager) to mint a token. `services/gateway_auth.py`.
      Live-tested against DashScope. `backend/tests/test_gateway.py` (12).
- [x] `backend/api/workstation.py` — `POST /workstation/tool-event`, persona-token
      auth, writes `AuditLog` (`action="tool_event"`). `backend/tests/test_workstation.py` (5).
      Shared identity dep in `backend/api/deps.py`.
- [x] Managed opencode config: `sandbox/managed-settings.json`
      (`@ai-sdk/openai-compatible` + `baseURL` = gateway, plugin, `permission` defaults).
- [x] `packages/agent-plugin/` — opencode plugin: `tool.execute.before` / `.after`
      / `permission.asked` → `POST /workstation/tool-event` (audit-only, no decision).
      Node `--test`, typecheck, 6 tests.
- [x] `sandbox/Dockerfile` v0 + `sandbox/run.sh` (roughest `3pa run`: build image,
      `docker run` with only the project mounted).
- [x] CI: `.github/workflows/gateway.yml`, `agent-plugin.yml`, `adr-guard.yml`.

**Remaining for a full demo:** pin opencode in the sandbox image (ADR-0012),
parse the final usage chunk on streamed gateway calls, an integration test that
boots opencode headless with the plugin.

---

## Phase 1 — Security core

**Goal:** policy is now actually enforced; the audit is tamper-evident; there is
basic injection defense.

- [x] `backend/services/policy_engine.py` (ADR-0005): pure `evaluate()` (ordered
      rules, last-match-wins, fail-closed on bad rule / bad request / bad default)
      + DB-backed `decide()` with a rollout mode (`off` / `dry_run` / `enforce`,
      default `dry_run`). Baseline catastrophic-command safety rules. Org rules
      parsed from fenced ```policy blocks in `Policy` markdown.
      `backend/tests/test_policy_engine.py` (32).
- [x] `agent_runtime.execute_skill` calls `decide()` before every tool call;
      `POST /policy/decide` (gateway) for the plugin; plugin `tool.execute.before`
      calls it and throws on an enforced `deny`/`ask`. Decisions audited.
- [x] CI: `.github/workflows/policy-engine.yml` (fail-closed + baseline golden set).
- [x] `backend/services/audit_chain.py` (ADR-0006): `AuditEvent` model +
      migration; `append()` (sha256 chain, `prev_hash` → `hash`), `record()`
      (chain + mirror a legacy `AuditLog` row), `verify()` (finds the first
      break), `ingest_batch()`. Endpoints `POST /audit/ingest` (persona token,
      one-way) and `GET /audit/chain/verify` (manager). Gateway calls, policy
      decisions, and tool events now all flow through it.
      `backend/tests/test_audit_chain.py` (12 — tamper detection for modified /
      deleted rows).
- [x] **Scoped enforcement** (company → department → agent): `decide()` resolves
      scope from the persona and gathers the applicable `Policy` bodies the same
      way `run_session` gathers names (company-scoped + `DepartmentPolicyLink` +
      `AgentPolicyLink`). New `PolicyConfig` table (migration `c3d5f7a9e1b2`) for
      per-scope `mode` / `default_effect`, most-specific-wins. `GET`/`PUT
      /policies/config`. **Fail-closed verdicts block in every mode**, only a
      clean matched deny/ask waits for `enforce`.
- [ ] `3pa`: stop opencode if the gateway/audit is unreachable (fail-closed).
- [ ] Provenance separation (ADR-0010): `web_search` / file / A2A output tagged
      `untrusted`; egress allowlist (sandbox network layer).

---

## Phase 2 — Identity, managed config, Postgres

- [ ] **Postgres — full migration** (decided): compose service, `database.py`
      fresh-DB detection (drop the `sqlite_master` check), pgvector for RAG
      (replaces `sqlite-vec`), cross-process write lock for the audit chain.
- [ ] **Per-tenant audit chain** — one chain per company, done together with the
      Postgres move (ADR-0006).
- [ ] **`bash` AST parsing** (`bashlex`) for the Policy Engine — before `enforce`
      is meaningful for shell (ADR-0005).
- [ ] `3pa login` — platform-local identity as the baseline; pluggable OIDC for
      orgs that bring their own IdP (`3pa login --oidc <issuer>`) (ADR-0007).
- [ ] `api/well_known.py` — `/.well-known/opencode`, signed org config (ADR-0011).
- [ ] Managed config in the container image; `3pa` signature verification.
- [ ] Backend MCP server (`api/mcp_server.py`): skills / A2A / inbox / policies
      exposed to opencode as tools.
- [ ] Gateway: model allowlist + per-persona quota + rate limit.
- [ ] **LLM severity check** (ADR-0013): background job scores recent audit
      events via an OpenAI-compatible endpoint; high risk → inbox / Telegram alert.
- [ ] Rule authoring UI.

---

## Phase 3 — Sandbox hardening + operations

- [ ] `sandbox/` : narrower mounts, egress-proxy allowlist, resource limits,
      devcontainer compatibility.
- [ ] `3pa doctor`, `3pa update`, heartbeat + sandbox digest attestation.
- [ ] Anomaly alerts (gateway: token spike, off-allowlist host; audit: heartbeat
      loss).
- [ ] CI: `fabctl.yml` (sandbox smoke), `e2e-nightly.yml` (full loop + chain
      verification).

---

## Phase 4 — Enterprise packaging

- [ ] Main-server install flow (on top of the existing `install.sh` / compose).
- [ ] Persona onboarding, `3pa` distribution via MDM.
- [ ] Migration to Postgres (audit + gateway volume).
- [ ] Output scanning (secret/PII), evaluation of a classifier layer (ADR-0010).
- [ ] Documentation: enforcement boundaries (ADR-0003) made clear to the customer.

---

## Next (phase-less backlog)

- Our own Bubble Tea TUI (ADR-0008) — when the need for an "operations panel"
  becomes concrete.
- Server-side execution as an optional deployment model (ADR-0002 option B) — for
  organisations that want "full enforcement".
- Applying `context-mode`-style approaches to agent context management (a
  separate evaluation).
