# Roadmap — Agentic OS layer

This document is the phased plan for moving the platform from **web-first agent
management** to a system where developers work on their own machines with a
sandboxed agent (opencode), all traffic goes through a central gateway, and
everything is logged tamper-evidently.

Full rationale for the decisions: [`docs/adr/`](adr/). Architecture picture:
[`docs/architecture/agentic-os.md`](architecture/agentic-os.md).

## Current state (2026-09-02)

**Phases 0–2 are on `main`.** Gateway + guardrails, fail-closed scoped Policy
Engine (with bash AST matching), per-tenant tamper-evident audit chain, full
Postgres cutover (pgvector), `3pa login` + pluggable OIDC, Ed25519-signed
`/.well-known/opencode`, backend MCP server, LLM severity scoring. 7 migrations
(head `b7d1e93a4c25`); CI includes a real-Postgres job (`postgres.yml`).

**ADR-0010 injection defense** (layers 1–4): plugin session-level provenance/taint
tracking, `baseline:untrusted-high-risk` policy rule, `sandbox/base-prompt.md`
structural guardrails, and a `FilterDefaultDeny` egress proxy on an internal-only
sandbox network (`sandbox/egress/` + `sandbox/compose.yaml`).

**ADR-0009 `3pa run` / `3pa doctor`**: launch opencode in the sandbox with a
fail-closed gateway/token preflight, Ed25519 verification + TOFU-pin of the
served org config (ADR-0011), token/model injection, and a gateway heartbeat.

**ADR-0007 token refresh + revocation**: access + refresh persona tokens (jti,
rotation on refresh), `POST /workstation/persona-token/refresh` + `/revoke`
(owner or self), fail-closed per-jti + per-persona `not_before` revocation
checked in the auth deps. `3pa refresh` / `3pa logout [--revoke]`; `3pa run`
auto-refreshes near expiry.

### Remaining, by ADR

| ADR | Left to do |
|-----|------------|
| 0002 | ~~egress-proxy + allowlist~~, ~~isolation hardening (cap_drop, no-new-privileges, pids/mem/cpu, OPENCODE_* scrub)~~ done; read-only rootfs, devcontainer/macOS |
| 0004 | ~~parse the streamed `usage` chunk~~ done; Redis rate-limit for multi-worker; propagate non-200 upstream status on the streaming path |
| 0005 | rule-authoring UI; parent-department policy inheritance |
| 0006 | external chain anchoring (git / S3 Object Lock); Redis cross-process lock |
| 0007 | ~~token refresh + server-side revocation~~ done; in-sandbox token rotation (long-run TTL limit); device registration; auto-revoke on plugin-heartbeat loss; prune expired revocation rows |
| 0008 | own Bubble Tea TUI (deferred until an "operations panel" need is concrete) |
| 0009 | ~~`3pa run`~~, ~~`3pa doctor`~~, ~~`3pa policy`~~, ~~`3pa audit verify`~~, ~~`/workstation/heartbeat`~~ done; `3pa update`; auto-revoke job; distribution + signing |
| 0010 | ~~provenance / taint separation~~, ~~structural prompt guardrails~~, ~~untrusted-turn → `ask`~~, ~~egress allowlist~~ done; signed command channel, output scanning still pending |
| 0011 | ~~fetch + verify + in-container injection + key rotation~~ done; `OPENCODE_PERMISSION` env-bypass hardening; plugin runtime assert; rotate UI |
| 0012 | ~~`release.yml` (sandbox/egress images, 3pa bundle, plugin/cli npm), opencode pin, compat matrix~~ done; backend/frontend image push; Go 3pa + signing; e2e-nightly |
| 0013 | Telegram wiring; per-company opt-in; feed high scores back into the Policy Engine |

**Suggested next work:** (1) ADR-0012 release workflows, (2) ADR-0010 signed
command channel, (3) ADR-0006 external chain anchoring.

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
- [x] Managed opencode config: `sandbox/opencode.json`
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

- [x] **Per-tenant audit chain** (ADR-0006): `AuditEvent` now keyed
      `(chain_key, seq)` — one chain per company, `__global__` for company-less
      events. Hash covers `chain_key` so rows can't be spliced between chains.
      `verify(company_id)` / `verify_all()`; `GET /audit/chain/verify?company_id=`.
      `append()` takes a PG transaction advisory lock (no-op on SQLite).
      Migration `d9b2f4c6a8e0` (rebuilds the table — dev-only, no prod data).
- [x] `database.py` fresh-DB detection is now dialect-agnostic (inspector, not
      `sqlite_master`); SQLite-only `check_same_thread` guarded; pool pre-ping /
      recycle for non-SQLite.
- [x] **RAG moved into the main DB** (`EmbeddingRecord` / `RagIndexState`,
      migration `e1a4c7d92f38`) — no more separate `data/rag.db`, `sqlite-vec`
      dropped. Search: pgvector (`<=>` + HNSW) on Postgres, NumPy brute-force
      cosine on SQLite. `test_rag.py` rewritten (13).
- [x] **Postgres compose**: `db` service (`pgvector/pgvector:pg16`) in base /
      prod / cloud compose; backend `DATABASE_URL` → Postgres, `depends_on`
      healthy. `.env.example` Postgres vars. `.github/workflows/postgres.yml` +
      `test_pg_smoke.py` (migrations → head, pgvector search, audit chain on real
      PG).
- [ ] SQLite→Postgres data migration guide for existing deployments (dump/load;
      not an Alembic concern).
- [x] **`bash` AST parsing** (`bashlex`) for the Policy Engine —
      `services/command_parser.py` + a `command` rule matcher (`program` /
      `args_all_of` / `args_any_of` / `any_program` / `pipes_into`). Baseline
      rules moved to it; immune to whitespace / split flags / `sudo` / `$(...)`.
      An unparseable command with a `command` rule present → fail closed.
      `test_command_parser.py` (10) + AST bypass-resistance tests (13).
- [x] `3pa login` (ADR-0007): `GET /workstation/personas` (owner-scoped),
      `POST /workstation/persona-token` (owner-scoped mint),
      `POST /workstation/oidc/exchange` (`services/oidc.py` — JWKS verify, email→User,
      no auto-provision, off unless `oidc.enabled`). `packages/cli` `login` command
      → `~/.config/3pa/session.json`; `sandbox/run.sh` reads it.
- [x] `api/well_known.py` — `GET /.well-known/opencode`, **Ed25519-signed** org
      config (`services/wellknown_sign.py`), `+ /pubkey` for pinning (ADR-0011).
- [ ] `3pa` fetches + verifies `/.well-known/opencode` and bakes it into the
      sandbox managed config; signing-key rotation.
- [x] Backend MCP server (`api/mcp_server.py`): JSON-RPC 2.0 `POST /mcp`
      (persona-token auth) — `initialize` / `tools/list` / `tools/call`. Exposes
      the persona's linked skills (reusing `build_tool_definitions` +
      `execute_skill`, so A2A / journal / db_query come for free) plus an
      `org_policies` read tool. Advertised in `/.well-known/opencode`.
- [x] Gateway guardrails (`services/gateway_limits.py`, migration
      `f2b8d1e4c690`): model allow-list (comma globs, company override, the
      persona's own model always allowed), per-persona rate limit (in-process
      sliding window), daily/monthly token quota (`GatewayUsage` table).
      `preflight()` before forwarding, `record_usage()` after. `GET
      /gateway/usage`. All limits default permissive (`dry_run` philosophy).
- [x] **LLM severity check** (ADR-0013): `services/audit_severity.py` — a 10-min
      APScheduler job (off unless `severity.enabled`); scores recent audit events
      via the org's OpenAI-compatible upstream, writes `AuditSeverity` (side
      table, chain untouched), score ≥ threshold → `InboxMessage` to the
      responsible human. Migration `a4e6c8b02d17`.
- [ ] Rule authoring UI; Telegram wiring for severity alerts; parse streamed
      `usage` chunks for exact token accounting.

---

## Phase 2 — done. Remaining glue for a full workstation demo

- [ ] `3pa run`: fetch + verify `/.well-known/opencode`, bake it into the
      in-container managed config, inject the persona token, heartbeat.
- [ ] Sandbox egress-proxy + allowlist (ADR-0010), fail-closed heartbeat (ADR-0006).
- [ ] SQLite → Postgres data-migration guide for existing deployments.
- [ ] Redis-backed rate limit + audit-chain lock for multi-worker.

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
