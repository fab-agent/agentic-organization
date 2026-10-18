---
sidebar_position: 99
---

# Release Notes

The platform's changes, newest first. For technical detail see the repository's commit history and `docs/adr/` records.

## v1.4 — 18 October 2026: Authorisation hardening, evaluation, monorepo

- **Change requests:** company and role checks, scope (a department head only for their own department), the same person cannot approve both stages, one winner on concurrent approval.
- **Invites and role grants:** who may grant which role is enforced in the API; an existing founder/executive membership cannot be lowered.
- **Evaluation (ADR-0023, stage 1):** run diagnosis from audit events and the `/eval` API. → [Evaluation](/workstation/eval)
- **Audit chain:** workstation events are stamped `origin: client` by the server; policy decisions carry the verified `run`.
- **Multi-company authorisation:** policies, skills, departments, memberships, flows, sessions, invites and token minting are tied to the role in the owning company; a chat session belongs to its owner and the agent's managers; a `draft` agent cannot be used; an invite never resets the password of an account that belongs to another company.
- **Gateway:** timeouts, connection errors, unparseable replies, cut streams and empty output are written to the audit event.
- **ADRs:** 0003, 0006, 0014–0023 accepted; some decisions of 0014 and 0019 are narrowed/superseded by ADR-0022.
- **Repository:** the documentation (`apps/docs`) and landing page (`apps/landing`) now live in this repository; the version number matches the code; the licence is Commons Clause + MIT in `LICENSE`.

**Limits:** judges, a viewer page and replay do not exist yet. → [Known limits](/developer-notes/known-limits)

## v1.3 — 30 September 2026: Department Workspace (`fab`)

The `fab` client in which every department works from the terminal, and the server side behind it.

- **`fab` client:** sign-in, sidebar, local agent pane, `fab workspace`, `fab sync`.
- **Workspace API:** create, resume, suspend, file manifest, single-use attach ticket.
- **One agent per person**, token-budgeted prompt assembly, company context and job description, intent classification with Jev (first turn only, fail-open, off by default).
- **Work review and fit ratings:** "My review", contesting, rubric and its linter, sampled rating, calibration tool, training-need signal. **Off** per company by default.
- 5 new database migrations; hourly/daily scheduled jobs.

**Limits:** there is no real workspace runtime (only a `FakeRuntime` for tests); rating has not been measured with live Jev and has not passed legal review. → [fab](/fab/overview)

## v1.2 — 9 September 2026: Developer Workstation

Software developers working on their own computers with **opencode**, inside a sandbox connected to the server. The web interface did not change; this layer works alongside it, optionally.

- **Central LLM gateway:** OpenAI-compatible, bring your own key; model allow-list, rate and token quota, usage metering.
- **Executable policy engine:** allow / ask / deny; denies on failure; `off`, `dry_run`, `enforce` modes.
- **Tamper-evident audit chain:** hash-chained record, external anchoring (S3 Object Lock / local log).
- **Identity:** short-lived persona tokens, refresh, revocation, sign-in with OIDC.
- **`3pa` CLI**, opencode plugin, signed managed configuration, sandbox and egress filter, prompt injection defense, LLM audit severity scoring and Telegram alerts.

→ [Developer Workstation](/workstation/overview)

## v1.1.2 — 15 July 2026

- License note updated. **Note:** on 18 July 2026 the `LICENSE` file was turned back to plain **MIT**; the "Commons Clause" wording is no longer valid.

## v1.1.1 — 14 July 2026

- AI provider settings were split into two sections: **local models** and **cloud API services**.
- **Delete** is now visible on a provider card with an invalid key; deleting prevents the key from being re-added from `.env`.
- Hard-coded Turkish text on the Dashboard moved into the translation system; the English title of the Organization page was fixed.

## v1.1 — 14 July 2026: Production readiness

- **One-command install** (`install.sh`) and the `.env` wizard (`setup-env.sh`); production Docker configuration and an HTTPS (Let's Encrypt) Nginx template.
- **New version notice:** the Dashboard checks the latest release on GitHub (1-hour cache).
- **Agent SLA table:** for each agent sessions, tokens, flow success and task completion rate.
- System requirements and production installation documentation.

## v1.0 — 14 July 2026

- **Local models:** Ollama and LM Studio became first-class providers; the server address is entered and models are fetched automatically.
- **Change request flow:** agent edits are not saved directly but enter the approval flow (`submitted → dept_head_approved → admin_approved → committed`), with a YAML commit to GitHub after approval.
- **Archiving:** archiving instead of deleting an agent (`inactive`); data is kept.
- The built-in tool list comes dynamically from the server.
- Security: a critical warning at startup with the default `JWT_SECRET`.

## v0.9 — 12 July 2026

- Token counting fixes (all tool steps are accumulated; Qwen fallback calculation).
- **Image generation** in flows (Qwen Image / Wanx / Flux); task routing now also considers the company skill library.
- Integration tests for GitHub, Telegram, PostgreSQL and scheduled flows.

## v0.8 — 9 July 2026

- **AI Setup:** web research + chat + preview + one-click creation.
- **Skills** and **Policies** pages (Markdown editor, change request flow).
- In the sidebar, the structure pages were gathered under **Structure**.

## v0.6 — 9 July 2026

- Dashboard rewritten: company and personal telemetry, memory summaries, company identity (vision, mission, values, goals).
- **Telegram** integration for invitation and password notifications; the provider screen was simplified; sidebar collapse.

## v0.5 — 9 July 2026

- **Security:** company membership check on all endpoints; password change required at first sign-in; typed input schemas.
- **Infrastructure:** Alembic migrations, JSON logs, production Docker/Nginx configuration (login limited to 5 requests per minute).
- **Backup** tab (S3-compatible) and **social media** skills (Instagram, WhatsApp).

## v0.4 — 2 July 2026

- Qwen (DashScope) provider; a **first-setup form** instead of a fixed admin password; interface languages limited to Turkish and English.

## v0.3 — 23 June 2026

- **Audit log:** a record of create, update and delete actions; Settings → Audit Log.

## v0.2 — 19 June 2026

- Persistent memory across agent sessions; tool calls in flows; Turkish and English interface.

## v0.1 — 1 June 2026

First release.

- Company, department, human and agent management; the org chart; five platform roles and the invitation system; authentication with JWT.
- Provider key management (Anthropic, OpenAI, Google, Mistral); an agent runtime with tool calls, skills, session history, MCP support.
- GitHub / GitLab / Gitea synchronization; invitation by email; delegation between agents (A2A).
- SvelteKit 5 interface, multi-company use, light/dark theme.
