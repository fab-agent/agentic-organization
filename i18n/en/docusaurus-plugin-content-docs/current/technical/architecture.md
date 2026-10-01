---
sidebar_position: 1
---

# Architecture

This section is for IT teams and developers. Business users can do with the [User Guide](/guide/onboarding).

## Components

```
 Browser ──► Nginx ──► Interface (SvelteKit)
                 └────► Backend (FastAPI) ──► PostgreSQL + pgvector
                              │
                              ├──► LLM providers (Anthropic, OpenAI, Google, Mistral, Qwen, local, custom)
                              ├──► External tools (MCP, HTTP, databases, Instagram/WhatsApp)
                              ├──► Telegram, Resend (email), S3-compatible storage, GitHub
                              │
 3pa + opencode ───► /v1 gateway, /workstation, /mcp   (developer workstation)
 fab (terminal) ───► /workspaces, /work-review         (department workspace)
```

| Component | Technology | Role |
|---|---|---|
| **Backend** | FastAPI, SQLModel, Alembic, APScheduler | API, agent runtime, scheduled jobs |
| **Interface** | SvelteKit 5 (Svelte runes), Tailwind, TR/EN | Web interface |
| **Database** | PostgreSQL 16 + pgvector (SQLite in development) | All data, semantic search |
| **`packages/cli`** | TypeScript | The `3pa` developer CLI |
| **`packages/agent-plugin`** | TypeScript | opencode plugin (policy, audit) |
| **`packages/tui`** | Rust, Ratatui | The `fab` terminal client |
| **`sandbox/`** | Docker | Developer sandbox and department workspace image |

## Repository layout

| Directory | Content |
|---|---|
| `backend/api/` | One router per resource (`auth`, `personnel`, `flows`, `a2a`, `gateway`, `workstation`, `work_review`, `workspaces` …) |
| `backend/services/` | Business logic: agent runtime, flow runner, policy engine, audit chain, RAG, Git, Telegram … |
| `backend/models.py` | All tables |
| `backend/migrations/` | Alembic migrations |
| `frontend/` | The SvelteKit application |
| `docs/adr/` | Architecture decision records ([index](/developer-notes/overview#architecture-decision-records-adr)) |
| `.github/workflows/` | CI per component |

## Data model (summary)

```
Company ──< Department ──< Personnel ──── Agent configuration ──< Skill
   │                           │                  │
   │                           │             Session ──< Message
   │                           │                  └── Memory (session summary), embedding vectors
   │
   ├── Policy (company | department | agent)
   ├── Flow (cron)  ·  Task request  ·  A2A request  ·  Inbox message
   ├── Change request (two-stage approval)
   ├── Provider key  ·  Git configuration  ·  Telegram  ·  Database connection
   └── User ──< Company membership (role)
```

The developer workstation and department workspace layers have their own tables (audit chain, token state, workspaces, work-review ratings). See the relevant sections.

## Startup and scheduled jobs

When the application starts, database migrations (Alembic) run, seed data is written on first install, and provider keys from the environment are imported. When running with several processes (workers), **only one process** runs the scheduler and Telegram polling (through a lock file); the others only serve requests.

The scheduler (UTC) runs these jobs:

| Job | Frequency |
|---|---|
| User flows | Each flow's own cron; the flow list is synchronized every minute |
| RAG indexer | Every 15 minutes (new session replies, task results, memories) |
| Audit severity scoring | Every 10 minutes (does nothing if switched off) |
| Work-review rollup / cleanup / rating | Hourly / daily / hourly (if the company enabled it) |

## Multi-tenant subdomains

You can give each company its own subdomain (`company.agent.mycompany.com`): a wildcard DNS record points to a single server, Nginx forwards all of them to the same application, and the interface resolves the company from the subdomain through `/tenant/resolve` (the company name appears on the sign-in page, and a nonexistent subdomain returns 404). Data is separated per company. For step-by-step setup see the `CLOUD_DEPLOY.md` file in the repository.

## Frontend notes

- **Svelte 5 runes.** State is managed with `$state`, `$derived`, `$effect`.
- **Company-reactive data loading.** Pages reload when the active company changes; so both the first load (`onMount`) and the company switch (`$effect`) are handled separately and `company_id` is passed to API calls.
- **i18n.** Two languages (`tr`, `en`); missing translations fall back to Turkish. The language choice is stored in the browser.
