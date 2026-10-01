---
sidebar_position: 1
---

# Developer Notes

This section is for people building and reviewing the platform: why we chose these technologies, which decisions we made, which ideas we discarded, and where we stand. Business users can skip it. Formal decisions on record are in `docs/adr/` in the repository; this is their summary and background.

## Technology choices

| Area | Choice | Why |
|---|---|---|
| Backend | FastAPI + SQLModel | Async, automatic OpenAPI, Pydantic validation; one model is both ORM and schema |
| Database | PostgreSQL 16 + pgvector (dev: SQLite) | It started on SQLite (single file, simple backup); moved to PostgreSQL for semantic search and multi-process operation |
| Interface | SvelteKit 5 + Tailwind | Small bundle, the runes system needs little boilerplate; the basic components (Button, Badge, Input…) are our own because shadcn-svelte was incompatible with Svelte 5 at the time |
| Scheduling | APScheduler (in-process) | No separate service like Celery + Redis; with several processes a single leader through a lock file |
| Git | PyGithub (GitHub Contents API) | A single HTTP call instead of managing clones on the server; SHA handling is automatic |
| Git authentication | Personal access token (PAT) | Enough for an MVP; OAuth (callback, secret management) postponed |

## Architecture decisions taken

- **Change requests are two-stage: department head → executive.** The idea "let the founder approve" was dropped because it did not scale. The department head looks at technical fit, the executive at corporate risk and policy. → [Change Requests](/guide/change-requests)
- **Task routing climbs the parent department chain.** First a skill match is looked for in the same department; if none is found, the `parent_id` chain is climbed. Organic routing instead of a central "general agent pool". → [Task Requests](/guide/tasks-and-inbox)
- **A single notification layer.** Flow results, task notifications and system messages drop into the same `InboxMessage` table; `source_type` tells them apart. Adding a new event type does not change the inbox code.
- **Human approval inside the agent chain.** Handing tasks between agents needs two human approvals; agents cannot run each other without a human. → [Delegation](/guide/delegation)
- **Developer and department layers are separate doors with a common core.** Same gateway, policy engine and audit chain; the surface changes with the person's job (opencode / `fab` / web).

## Architecture decision records (ADR)

| ADR | Topic | Status |
|---|---|---|
| 0001 | opencode as the developer client | accepted |
| 0002 | Execution model: laptop + mandatory local sandbox | accepted |
| 0003 | Threat model and enforcement boundaries | proposed |
| 0004 | Central LLM gateway (OpenAI-compatible, bring your own key) | accepted |
| 0005 | Executable policy engine (denies on failure) | accepted |
| 0006 | Tamper-evident (hash-chained) audit | proposed (implemented) |
| 0007 | Agent identity and short-lived credentials | accepted |
| 0008 | TUI strategy | accepted; TUI technology changed by ADR-0014 |
| 0009 | The `3pa` workstation CLI | accepted |
| 0010 | Prompt injection defense | accepted |
| 0011 | Managed configuration and precedence | accepted |
| 0012 | Repository structure and release process | accepted |
| 0013 | LLM audit severity scoring | accepted |
| 0014 | A terminal workspace for every department (`fab`) | proposed |
| 0015 | Ingesting company documents (Docling) and ranking (Jev) | proposed, no code |
| 0016 | Installation kit: org chart, identity, models, company systems | proposed |
| 0017 | Policies as code (versioned) and daily work review | proposed, no code |
| 0018 | Workspace lifecycle API | proposed |
| 0019 | One agent per person and work review | proposed |
| 0020 | Token-budgeted prompt and intent breakdown | proposed |
| 0021 | The fit rubric | proposed |

0014 and 0018–0021 are largely implemented but their status is still `proposed`; they await an acceptance decision. Details and next jobs: `docs/ROADMAP.md` in the repository.

## Planned: managing policies with a local git system

Today the Git integration is tied to GitHub (change-request commits). The planned direction (ADR-0017): versioning company policies, the rubric and agent configurations in the **company's own local git system**, like a code library; changes going through the change-request flow; git being the "source of truth" and the database a cache that can be rebuilt from it. This has not been written yet.

## Strategy notes (summary of the September 2026 discussion)

**Making policy documents operational (Docling + Jev).** The idea of ingesting large companies' hundreds of policy documents with Docling, moving guardrails outside the context window, and checking them with TypeSafe AI "Jev" was researched. Findings:

- Jev is a classifier that **does not generate text** (it gives a probability for typed questions). It separated clear violation/compliance cases very well; it was **inconsistent on ambiguous cases**. So it is used not as a sole decision maker but as a "referee", together with human oversight.
- Docling extracts PDFs much more cleanly than `pypdf` but needs a **cleaning layer** for heading/footer repetition.
- **Semantic errors** were seen in summaries produced by an LLM, such as writing a "permission limit" as an "obligation"; quote matching alone is not enough.
- Running a local model on this server is not possible (no GPU); providers stay external.
- **Real company documents** must not be sent to Jev before its privacy/retention terms are verified.

**Interposing between tools instead of replacing them.** The goal is not to replace the tools employees use (opencode, similar developer tools, later chat applications) but to sit between them and make usage, cost and compliance visible. Two tiers:

- **Tier A:** tools whose address (base URL) is configurable. A natural extension of the existing gateway; low risk. **This first.**
- **Tier B:** SaaS chat applications (interposing/MITM). It means entering the AI-DLP/CASB market: months of separate engineering and legal weight. It stays on the roadmap, limited to a small pilot.

**A MAC address does not work as device identity** (it can be spoofed, it is layer 2 so a cloud server cannot see it, and operating systems randomize it by default). The right answer is a device certificate + SSO. For hierarchical reporting, `CompanyMember.role/scope_id` and the policy engine's department chain are already ready.

**The human-usage signal is separate from agent audit.** For agents the audit chain is part of injection defense; for human employees a lighter, **asynchronous and advisory** signal is needed (it does not block). In the web chat flow there is already a hook point on the server side right before the message goes to the model; one can start from here without needing Tier B.

**The classification schema should not be fixed, but not fully autonomous either.** The taxonomy and Jev questions should be **generated** from each company's own documents, but putting them into use must be **human-approved** (`draft` → `active`). The measured errors (above) make full autonomy indefensible. This is the same logic as the existing `dry_run → enforce` and change-request patterns. The rubric design in ADR-0021 (draft → shadow → live) applies this principle.

## Development and verification

```bash
# Backend (~6 min)
cd backend && ruff check . && ruff format --check . && python -m pytest -q

# fab (Rust)
cd packages/tui && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

Things to watch:

- **If a new migration adds a table**, add it to the `added_since` list in `backend/tests/test_pg_smoke.py`; if it adds a column to an existing table, it must be dropped there. Otherwise the PostgreSQL CI check breaks with "relation already exists".
- **From scratch on SQLite the whole Alembic chain does not work** (because of an old migration). To try it: `create_all` + `alembic stamp <previous revision>` + `upgrade head`.
- Architecturally significant file changes need an ADR (the `adr-guard` workflow); if not needed, the `no-adr-needed` label is put on the PR.
- **Keys** are given only as environment variables; they are not written to files or commits. If a key leaked to a chat/record, treat it as compromised and rotate it.
