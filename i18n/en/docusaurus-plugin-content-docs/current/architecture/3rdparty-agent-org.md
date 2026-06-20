---
sidebar_position: 1
---

# Architecture: 3rdParty Agent Organization

## Overview

| Layer | Technology | Notes |
|---|---|---|
| **Backend** | FastAPI + SQLModel + SQLite | Modular router structure |
| **Frontend** | SvelteKit 5 + Tailwind CSS | Svelte 5 runes (`$state`, `$derived`, `$effect`) |
| **Encryption** | Fernet (AES-256) | For API keys and Git tokens |
| **Git** | GitPython | YAML-based synchronization |
| **CLI** | TypeScript + @clack/prompts | Setup wizard |
| **Deployment** | Docker Compose | Full stack with a single command |

---

## Folder Structure

```
3rdparty-agent-org/
├── backend/
│   ├── main.py              # Router registration + startup hooks
│   ├── models.py            # SQLModel ORM models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── database.py          # SQLite engine + session context manager
│   ├── seed.py              # Sample data on first launch (2 companies)
│   ├── api/
│   │   ├── companies.py        # Company CRUD + stats
│   │   ├── departments.py      # Department CRUD (parent_id hierarchy)
│   │   ├── personnel.py        # Personnel + AgentConfig + Skill CRUD
│   │   ├── providers.py        # AI provider key management
│   │   ├── git_sync.py         # Git pull/push/diff/logs
│   │   ├── change_requests.py  # Change Request approval flow
│   │   ├── flows.py            # Autonomous Flows (cron scheduler)
│   │   ├── inbox.py            # Inbox messages
│   │   └── task_requests.py    # Task Requests + agent matching
│   ├── core/
│   │   └── security.py      # Fernet encryption/decryption
│   └── services/
│       ├── provider_service.py   # API key testing (httpx)
│       └── git_service.py        # GitPython operations + YAML I/O
│
├── frontend/
│   └── src/
│       ├── lib/
│       │   ├── api/             # Type-safe fetch clients
│       │   │   ├── client.ts    # Base fetch wrapper
│       │   │   ├── companies.ts
│       │   │   ├── departments.ts
│       │   │   ├── personnel.ts
│       │   │   ├── orgtree.ts
│       │   │   ├── providers.ts
│       │   │   └── git.ts
│       │   ├── components/ui/   # Bespoke components (Button, Dialog, Badge...)
│       │   ├── i18n/            # TR/EN/DE/ES translation dictionaries
│       │   └── stores/
│       │       └── company.svelte.ts  # Active company state
│       └── routes/
│           ├── +layout.svelte   # Company switcher + language selector + nav
│           ├── +page.svelte     # Dashboard
│           ├── departments/
│           ├── personnel/
│           ├── org-chart/
│           └── settings/        # AI providers + Git
│
├── packages/cli/             # `3pa` CLI wizard
├── data/                     # SQLite DB + Git cache
└── docker-compose.yml
```

---

## Data Model

```
Company
  ├── id, name, slug, sector, website
  │
  ├──< Department (company_id FK)
  │      ├── id, name, slug, description, goals
  │      ├── parent_id FK → Department (self-referential, null = root unit)
  │      └── policies_json  (JSON array)
  │
  └──< Personnel (company_id FK)
         ├── id, name, slug, title, role, type (human|agent)
         ├── department_id FK → Department
         ├── manager_id FK → Personnel (self-referential)
         │
         └── AgentConfig (1:1)
                ├── model, model_version, status (draft|active|inactive)
                ├── responsible_id FK → Personnel
                └──< Skill
                       └── name, version, description
```

Additional tables:

| Table | Purpose |
|---|---|
| `AppConfig` | Platform-wide key-value settings |
| `ProviderKey` | Encrypted AI API keys |
| `GitConfig` | GitHub PAT connection settings (per company) |
| `SyncLog` | Pull/push/commit history |
| `ChangeRequest` | Change Request (status, approval timestamps, commit SHA) |
| `Flow` | Autonomous Flow definition (schedule, prompt, enabled) |
| `InboxMessage` | Inbox messages (source type, read status) |
| `TaskRequest` | Task Request (filters, assigned agent, responsible user) |

---

## Backend Architecture

### Router Structure

`main.py` acts as a thin orchestrator:

```python
app.include_router(companies_router)    # /companies
app.include_router(dept_router)         # /departments
app.include_router(personnel_router)    # /personnel + /org-tree
app.include_router(providers_router)    # /providers
app.include_router(git_router)          # /git
```

Each router is defined with its own prefix. Routes are defined with `""` (empty string) rather than `/` to avoid trailing slash issues.

### Startup Hooks

On application start, in order:
1. `init_db()` — Tables are created (if they don't exist)
2. `run_seed()` — Sample data is loaded (if tables are empty)
3. `_sync_env_config()` — `.env` → `AppConfig` table
4. `_sync_env_provider_keys()` — `.env` API keys are encrypted and saved

### Security

- API keys and Git tokens are encrypted with Fernet (AES-256)
- The encryption key is stored in `data/.secret` (chmod 600)
- Plain-text keys are never returned in API responses

---

## Frontend Architecture

### Svelte 5 Runes

State management is handled with Svelte 5 runes:

```typescript
// stores/company.svelte.ts
let _list = $state<Company[]>([]);
let _active = $state<Company | null>(null);

export const companyStore = {
  get list() { return _list; },
  get active() { return _active; },
  async load() { ... },
  setActive(c: Company) { _active = c; },
  async create(name: string) { ... },
};
```

### i18n

The translation system is built on a reactive locale state:

```typescript
// i18n/index.svelte.ts
let _locale = $state<Locale>('tr');

export const i18n = {
  get locale() { return _locale; },
  set locale(v: Locale) { _locale = v; },
  t(key: TranslationKey): string { ... }
};
```

Supported languages: TR / EN / DE / ES (~50 translation keys)

### Company Filtering

All list pages (`departments`, `personnel`, `org-chart`) fetch data filtered by the active company:

```typescript
departments = await deptApi.list(companyStore.active?.id);
```

---

## Git Synchronization Service

The `GitSyncService` class manages bidirectional synchronization:

**DB → YAML (Push):**
- All agent records are exported in `agents/{slug}/agent.yaml` format
- Changes are sent to the repository via `git add + commit + push`
- If `auto_pr=True`, a PR is opened instead of a direct push

**YAML → DB (Pull):**
- The repository is cloned/fetched
- YAML files are parsed and upserted (matched by slug)
- All operations are recorded in the `SyncLog` table

---

## Platform Scope

| Component | Description |
|---|---|
| Organization management | Company + department hierarchy + personnel CRUD |
| AI providers | Fernet-encrypted API key management (Gemini / Anthropic / OpenAI) |
| CLI | `3pa init` setup wizard |
| Git integration | Pull/push/diff/PR, YAML I/O, GitHub PAT |
| Multi-company | Company switcher + i18n (TR/EN/DE/ES) |
| Skill system | `builtin \| mcp \| http \| function` types, `config_json` schemas, `is_active` flag |
| Agent runtime | SSE streaming, multi-provider routing, agentic loop (max 8 iter.) |
| Chat UI | Markdown/Mermaid rendering, agent info panel |
| A2A delegation | Two-stage approval flow |
| Authentication | JWT + invitation system, role hierarchy, profile page |
| Operational modules | Department hierarchy, Change Requests, GitHub commit integration, Autonomous Flows (cron), Task Requests, Inbox |

---

## Related Documents

- [Installation](../getting-started/installation.md)
- [Usage Guide](../getting-started/agent-usage.md)
- [Provider Key Management](./provider-key-management.md)
- [Agent Runtime Architecture](./runtime.md)
- [Skill Types](./skill-types.md)
- [A2A Collaboration Architecture](../product/a2a-architecture.md)
