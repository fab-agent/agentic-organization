# Agentic Organization

Self-hosted platform for companies to manage AI agents as first-class members of their org chart.

Define agents per personnel, assign skills and policies, run autonomous flows, and onboard your entire organization in a single AI-assisted conversation.

---

## Features

| Feature | Status |
|---|---|
| Multi-company management | ✅ |
| Department + personnel CRUD | ✅ |
| Agent configuration (model, skills, status) | ✅ |
| **AI Onboarding** — web search + AI chat → full org structure in minutes | ✅ |
| **Company Skills Library** — Markdown-based skill definitions assignable to multiple agents | ✅ |
| **Policies Management** — company / department / agent-scoped policies with Markdown editor | ✅ |
| Org chart visualization (interactive tree view) | ✅ |
| AI provider key management (Anthropic, OpenAI, Google Gemini, Mistral, Qwen, Ollama, LM Studio) | ✅ |
| **Autonomous Flows** — cron-scheduled agent tasks delivered to inbox | ✅ |
| **Task Requests** — route tasks to best-matched agent by dept + skill | ✅ |
| **Agent-to-Agent (A2A) delegation** with human approval + auto-compilation | ✅ |
| **Orchestrator agents** — Council Agent pattern with parallel specialist delegation | ✅ |
| **Token telemetry** — per-message token tracking across all providers | ✅ |
| **Long-term agent memory** — session summaries stored and injected into future context | ✅ |
| **Image generation in flows** — Qwen Image / DALL-E via DashScope task API | ✅ |
| Real-time AI chat sessions (SSE streaming) | ✅ |
| First-time setup wizard (no hardcoded credentials) | ✅ |
| JWT auth + bcrypt passwords + Fernet-encrypted provider keys | ✅ |
| Audit log | ✅ |
| Multi-language support (TR / EN) | ✅ |
| Company-level authorization (multi-company users) | ✅ |
| Structured JSON logging (logs/app.log) | ✅ |
| Database migrations (Alembic) | ✅ |
| Login rate limiting (Nginx) | ✅ |
| On-demand backup to S3/R2/MinIO (Settings → Backup) | ✅ |
| Social media agent skills (Instagram Business + WhatsApp Cloud API) | ✅ |
| Telegram notification integration | ✅ |
| GitHub / GitLab / Gitea sync (config + policy Markdown files) | ✅ |
| Live dashboard — company + personal telemetry (tokens, sessions, memories, A2A SLA) | ✅ |
| Change request workflow — dept-head + admin two-step approval with Git commit | ✅ |
| ERP / custom database query skills — agents query live databases via SQL | ✅ |
| PostgreSQL + pgvector (RAG over agent memories, sessions and task history); SQLite for local dev | ✅ |
| Multi-tenant subdomains (`<company>.agent.fab.engineering`) — see [CLOUD_DEPLOY.md](CLOUD_DEPLOY.md) | ✅ |
| Multi-worker safe startup (single scheduler leader, serialized DB init) | ✅ |
| **Agentic OS layer** — gateway, policy engine, tamper-evident audit, `3pa` CLI + sandbox (see below) | ✅ |

---

## Agentic OS Layer (Developer Workstations)

The web UI stays the main surface for non-developer staff. Developers can additionally run
[opencode](https://opencode.ai) on their own machine, inside a sandbox, with every model call
and tool call going through this server:

| Component | Where | What it does |
|---|---|---|
| **LLM Gateway** | `backend/api/gateway.py` | OpenAI-compatible `/v1/chat/completions` + `/v1/models`; per-persona token → company provider key; model allowlist, quota, rate limit, usage telemetry |
| **Policy Engine** | `backend/services/policy_engine.py` | Fail-closed `allow / ask / deny` for skills and tool calls, bash AST matching, parent-department inheritance |
| **Tamper-evident audit** | `backend/services/audit_chain.py`, `audit_anchor.py` | Per-tenant hash chain, external anchoring (local log / S3 Object Lock), `3pa audit verify` |
| **LLM severity scoring** | `backend/services/audit_severity.py` | Scores audit events, Telegram alerts, per-company opt-in, policy auto-escalation |
| **Persona tokens** | `backend/services/gateway_auth.py`, `api/workstation.py` | Short-lived access + refresh tokens, rotation, revocation, heartbeat, optional OIDC exchange |
| **Signed config** | `backend/api/well_known.py` | Ed25519-signed `/.well-known/opencode`, plus API catalog, A2A agent card and `/auth.md` |
| **MCP server** | `backend/api/mcp_server.py` | Exposes skills / A2A / inbox / policies to opencode over MCP |
| **Signed command channel** | `api/workstation.py` | Server → workstation commands, signed and acknowledged |
| **`3pa` CLI** | `packages/cli` | `init`, `login`, `run`, `doctor`, `policy`, `audit`, `refresh`, `logout`, `status`, `start`, `stop` |
| **Org plugin** | `packages/agent-plugin` | opencode plugin: policy check before each tool, audit reporting, taint tracking |
| **Sandbox** | `sandbox/` | Container image + default-deny egress proxy; only the project directory is mounted |

Design and rationale: [`docs/ROADMAP.md`](docs/ROADMAP.md), [`docs/architecture/agentic-os.md`](docs/architecture/agentic-os.md),
[`docs/adr/`](docs/adr/) (ADR-0001 … ADR-0013).

---

## Terminal workspace (`fab`)

Every department works from a terminal workspace where one agent per person does the tool
work: a Rust + Ratatui client (`packages/tui`, [`fab`](packages/tui/README.md)) on top of
per-person server-side workspaces, prompt assembly with intent classification, and an
opt-in work review with fit ratings that the person sees first. Decisions:
[ADR-0014](docs/adr/0014-department-terminal-workspace.md),
[0018](docs/adr/0018-workspace-lifecycle-api.md),
[0019](docs/adr/0019-one-agent-per-person-and-work-review.md),
[0020](docs/adr/0020-prompt-assembly-and-intent-breakdown.md),
[0021](docs/adr/0021-fit-rubric.md).

**Status:** works end to end against a fake workspace runtime and is tested; there is no real
workspace runtime yet, and fit rating has not been measured against the live Jev API or reviewed
legally, so it ships switched off. What is built, what is not, and the next steps:
[`docs/DURUM.md`](docs/DURUM.md) (Turkish).

---

## AI Onboarding

Instead of manually setting up departments, agents, skills and policies one by one, a conversational AI assistant does it for you:

1. **Web Search** — the system automatically researches your company online for context
2. **Guided Chat** — the AI asks 3–5 targeted questions about your team size, recurring workflows, tools used, and data sensitivity constraints
3. **Preview** — a complete org structure is generated and shown before anything is written to the database
4. **One-click Create** — departments, human personnel, AI agents, skills (with full Markdown content), and policies are all created in a single transaction

To start: **Settings → AI ile Kur** (requires at least one active AI provider key).

---

## Agent-to-Agent (A2A) Delegation

The platform supports multi-agent orchestration through a human-in-the-loop delegation flow:

1. An **orchestrator agent** (e.g. Council Agent) receives a task and delegates sub-tasks to specialist agents
2. A designated human approves each delegation before execution
3. Specialist agents run in parallel and report results
4. Results are automatically compiled into an executive report and posted back to the originating session

Flow: `pending_approval → running → completed → [auto-compiled report]`

Human approval is required at the delegation step. Results are auto-completed and compiled without additional approval gates.

---

## Autonomous Flows

Cron-scheduled agent tasks that run independently and deliver results to the responsible user's inbox.

- Any agent can have one or more flows (e.g., every 15 min, every 30 min)
- Flows support all configured providers (Anthropic, OpenAI, Google, Mistral, Qwen, Ollama, LM Studio)
- Image generation flows route automatically to DashScope task API when an image model is detected
- Results land in the inbox (and Telegram, if configured) and update flow telemetry (last run, status, output snippet)
- With several uvicorn workers, only the worker holding `data/scheduler.lock` runs cron jobs, so a flow never fires twice

---

## Quick Start

### Requirements

- Docker + Docker Compose **or** Python 3.11+ and Node.js 20+
- At least one active AI provider API key (Anthropic, OpenAI, Google, Mistral, Qwen, or a local model via Ollama / LM Studio)

---

### Option A — Docker (Recommended)

```bash
git clone https://github.com/fab-agent/agentic-organization.git
cd agentic-organization

cp backend/.env.example backend/.env
# Edit .env — JWT_SECRET is required (openssl rand -hex 32), AI provider keys are optional

docker compose up --build
```

This starts PostgreSQL 16 + pgvector (`db`), the backend and the frontend.

UI → `http://localhost:5173`  
API → `http://localhost:8000`

**Production (Nginx + PostgreSQL, 2 uvicorn workers):**

```bash
bash install.sh     # checks Docker, runs setup-env.sh (root .env), renders nginx.conf, starts the stack
# or, with .env and nginx.conf already in place:
docker compose -f docker-compose.prod.yml up -d --build
```

UI + API → `http://localhost` (Nginx on port 80/443, API under `/api`)  
Login endpoint is rate-limited to 5 attempts/minute per IP. The root `.env` must set
`POSTGRES_PASSWORD` and a strong `JWT_SECRET` — with `ENVIRONMENT=production` the backend
refuses to start on a placeholder or short secret.

For the multi-tenant subdomain setup see [CLOUD_DEPLOY.md](CLOUD_DEPLOY.md) (`docker-compose.cloud.yml`).

---

### Option B — Manual (Development)

**Backend:**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn main:app --port 8000
```

Without `DATABASE_URL` the backend uses SQLite (`data/app.db`) — fine for development. Production,
pgvector search and the Postgres smoke tests use `DATABASE_URL=postgresql+psycopg2://…`; the `db`
service from `docker-compose.yml` exposes one on `127.0.0.1:5432`.

Dependencies are locked: edit `backend/requirements.in` (runtime) or
`backend/requirements-dev.in` (test/lint), then regenerate the pinned
`requirements*.txt` with the `uv pip compile` commands at the top of
`requirements.in`. Never edit the `.txt` lockfiles by hand.

**Frontend (separate terminal):**

```bash
cd frontend
npm install
cp .env.example .env          # VITE_API_URL=http://localhost:8000
npm run dev                   # http://localhost:5173
```

---

### Option C — HTTPS with Cloudflare Tunnel (Recommended for Production)

No port forwarding or SSL certificates needed. Cloudflare Tunnel handles everything.

```bash
# 1. Install cloudflared
curl -L https://pkg.cloudflare.com/cloudflare-main.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install cloudflared

# 2. Login and create tunnel
cloudflared tunnel login
cloudflared tunnel create my-org-platform

# 3. Create config at ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml << EOF
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: app.your-domain.com
    service: http://localhost:80
  - service: http_status:404
EOF

# 4. Route DNS
cloudflared tunnel route dns my-org-platform app.your-domain.com

# 5. Start
cloudflared tunnel run my-org-platform
```

The production stack builds the frontend with `VITE_API_URL=/api`, so the UI and API share the
tunnel hostname — no rebuild needed. Set `APP_URL=https://app.your-domain.com` in `.env` so invite
links and CORS use the public origin.

---

## First Launch

On first open, a setup wizard asks for:
- Full name
- Company name
- E-mail
- Password

This creates the founder account. No hardcoded credentials — every install gets its own admin.

---

## Usage Guide

### 1. AI Onboarding (Recommended First Step)

Go to **Settings → AI ile Kur**. The wizard searches the web for your company, asks questions about your team and workflows, generates a preview, and creates everything with one click.

### 2. Company Management

Switch between companies or create a new one with the **"Add Company"** button in the navbar. Each company has its own departments, personnel, agents, skills, and policies.

### 3. Department Management

Add departments with name, slug, description, goals, and policies. Supports nested hierarchy via `parent_id`.

### 4. Personnel Management

The **Personnel** page lists both human employees and agents. When adding personnel, choose type (Human or Agent), assign a department and manager.

### 5. Agent Configuration

Departments, Personnel, Agents, Skills and Policies are tabs under **Yapı / Structure** in the sidebar.

On the **Agents** page: choose a model, set status (draft / active / inactive), and assign skills from the company skills library.

### 6. Skills Library

Company-wide skill definitions with full Markdown content. Assign to multiple agents via `AgentSkillLink`. Skills created during AI Onboarding appear here automatically.

### 7. Policies

Create policies scoped to **company**, **department**, or **agent** with a full Markdown editor.

### 8. Org Chart

The **Org Chart** page shows the full personnel hierarchy as an interactive tree. Click any agent node to open a detail panel with model, status, assigned skills, and linked policies.

### 9. Autonomous Flows

Under **Agents → [Agent] → Flows**: create cron schedules (e.g., `*/15 * * * *`) with a prompt. The agent runs automatically and delivers results to the responsible human's inbox.

### 10. Task Requests

Anyone in the org submits a task from the **Inbox** page (`/inbox`, backed by `/task-requests`). The system routes it to the best-matched agent by department and skill filter; the responsible human runs or rejects it, and the result streams back into the inbox.

### 11. Agent-to-Agent (A2A) Delegation

Configure **Council Agent** with specialist delegate skills. When given a task, it assigns sub-tasks to specialist agents (Lead Scout, Finance Copilot, CRM Steward, etc.). Humans approve each delegation. Results are automatically compiled into a final executive report.

View pending delegations under **İşler / Jobs → Delegasyon / Delegation** (`/a2a`).

### 12. AI Provider Management

Under **Settings → AI Sağlayıcılar**:

| Provider | Default models |
|---|---|
| Anthropic (Claude) | claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5 |
| OpenAI (GPT) | gpt-4o, gpt-4o-mini, o1-mini, o3-mini |
| Google (Gemini) | gemini-2.5-pro, gemini-2.0-flash |
| Mistral AI | mistral-large, mistral-small, codestral |
| Alibaba Qwen | qwen-max, qwen-plus, qwen-turbo, qwen-long (+ qwen-image models via DashScope) |
| Ollama (Local) | any model running locally |
| LM Studio (Local) | any model running locally |

When a key is present, the live model list is fetched from the provider. The defaults live in
`backend/services/provider_service.py`. Keys are stored encrypted (Fernet) — never returned as plain text.

### 13. Dashboard

The **Panel** page shows:
- **Company telemetry** (agent count, sessions, token usage, memory count)
- **Personal telemetry** (your agents' sessions, token consumption, long-term memory)
- **Agent SLA table** — per-agent sessions, tokens, flow success, A2A task completion rate

---

## Architecture

```
agentic-organization/
├── backend/                     # FastAPI + SQLModel (PostgreSQL + pgvector; SQLite for dev)
│   ├── main.py                  # App startup, router registration, scheduler (leader-only)
│   ├── models.py                # SQLModel tables
│   ├── schemas.py               # Pydantic request/response schemas
│   ├── database.py              # Engine + session, create_all / alembic upgrade
│   ├── requirements.in / .txt   # Runtime deps (loose → locked with uv pip compile)
│   ├── requirements-dev.in/.txt # pytest, pytest-cov, ruff
│   ├── api/
│   │   ├── auth.py              # Login, invite, setup wizard, JWT
│   │   ├── demo_auth.py         # Demo tenant OTP login
│   │   ├── users.py             # User + CompanyMember management (founder-only)
│   │   ├── companies.py         # Company CRUD + stats
│   │   ├── tenant.py            # Subdomain slug → company resolution
│   │   ├── departments.py       # Department CRUD + tree
│   │   ├── personnel.py         # Personnel + agent config + org-tree
│   │   ├── skills.py            # CompanySkill CRUD + AgentSkillLink assign/unassign
│   │   ├── policies.py          # Policy management
│   │   ├── onboarding.py        # AI Onboarding (search / chat / generate / create)
│   │   ├── sessions.py          # AI chat sessions + SSE streaming
│   │   ├── flows.py             # Autonomous flow scheduling (APScheduler)
│   │   ├── task_requests.py     # Task routing + human approval
│   │   ├── a2a.py               # Agent-to-Agent delegation + auto-compilation
│   │   ├── inbox.py             # Inbox messages
│   │   ├── journal.py           # Work journal per personnel
│   │   ├── change_requests.py   # Two-step approval → GitHub commit
│   │   ├── git_sync.py          # GitHub / GitLab / Gitea config sync
│   │   ├── providers.py         # AI provider key management
│   │   ├── database.py          # External DB connections for SQL query skills
│   │   ├── social_media.py      # Instagram / WhatsApp credentials + publish
│   │   ├── telegram_config.py   # Telegram bot configuration
│   │   ├── telegram_bot.py      # Telegram webhook — interactive agent interface
│   │   ├── backup.py            # On-demand backup to S3-compatible storage
│   │   ├── dashboard.py         # Live telemetry + SLA metrics
│   │   ├── audit.py             # Audit log (read-only)
│   │   ├── system.py            # /system/version
│   │   ├── gateway.py           # ── Agentic OS: OpenAI-compatible LLM gateway
│   │   ├── workstation.py       #    persona tokens, heartbeat, audit ingest, commands, OIDC
│   │   ├── mcp_server.py        #    MCP server for opencode
│   │   └── well_known.py        #    signed /.well-known/opencode, API catalog, agent card
│   ├── core/
│   │   ├── security.py          # Fernet encryption (data/.secret)
│   │   ├── runtime.py           # ENVIRONMENT, CORS origins, scheduler leader + startup locks
│   │   └── logging.py           # Structured JSON logging
│   ├── services/
│   │   ├── agent_runtime.py     # AI execution engine (multi-provider streaming, tools, tokens)
│   │   ├── provider_service.py  # Provider configs, key testing, model lists + pricing
│   │   ├── memory_service.py    # Session summaries → AgentMemory
│   │   ├── rag_service.py       # Local embeddings, pgvector search
│   │   ├── flow_runner.py       # Cron executor (image generation, Telegram notify)
│   │   ├── mcp_client.py        # MCP client (SSE / HTTP) + built-in skills
│   │   ├── onboarding_agent.py  # Web search + LLM conversation + bulk org creation
│   │   ├── database_service.py  # External database queries
│   │   ├── git_service.py, github_commit.py
│   │   ├── social_media.py, telegram.py, email.py
│   │   ├── policy_engine.py, command_parser.py        # ADR-0005
│   │   ├── audit_chain.py, audit_anchor.py            # ADR-0006
│   │   ├── audit_severity.py                          # ADR-0013
│   │   ├── gateway_auth.py, gateway_limits.py         # ADR-0004 / ADR-0007
│   │   ├── persona_revocation.py, oidc.py             # ADR-0007
│   │   └── wellknown_sign.py                          # ADR-0011
│   ├── migrations/              # Alembic migration scripts
│   └── tests/                   # pytest (SQLite; test_pg_smoke.py runs on Postgres in CI)
│
├── frontend/                    # SvelteKit 2 + Svelte 5 (runes) + Tailwind
│   └── src/
│       ├── lib/
│       │   ├── api/             # Typed fetch clients
│       │   ├── components/      # OrgChartNode, AgentDetailPanel, MessageContent, ui/
│       │   ├── i18n/            # TR / EN dictionaries
│       │   └── stores/          # auth, company, tenant
│       └── routes/
│           ├── setup/ login/ set-password/ profile/
│           ├── +page.svelte     # Dashboard (Panel)
│           ├── departments/ personnel/ agents/ skills/ policies/   # "Yapı / Structure" tabs
│           ├── org-chart/       # Interactive org tree with agent detail panel
│           ├── onboarding/      # AI Onboarding wizard
│           ├── chat/            # Agent chat sessions ("İşler / Jobs")
│           ├── a2a/             # Delegation queue + approval
│           ├── inbox/           # Inbox + task requests
│           ├── flows/           # Autonomous flow management
│           ├── change-requests/ # Two-step approval workflow
│           └── settings/        # Providers, Telegram, social media, Git, databases, backup
│
├── packages/
│   ├── cli/                     # `3pa` workstation CLI (ADR-0009)
│   └── agent-plugin/            # opencode org plugin (policy, audit, taint tracking)
├── sandbox/                     # opencode container + default-deny egress proxy (ADR-0002)
├── docs/                        # ROADMAP.md, architecture/, adr/
└── .github/workflows/           # ci, postgres, gateway, policy-engine, cli, agent-plugin,
                                 # sandbox, release, adr-guard
```

### Data Model

```
Company ──< Department ──< Personnel ──── AgentConfig ──< AgentSkillLink ──> CompanySkill
   │                            │              │
   │                            │         AgentSession ──< SessionMessage (tokens_used)
   │                            │              │
   │                            │         AgentMemory (long-term session summaries)
   │                            │         EmbeddingRecord (RAG vectors)
   │                            │
   │                     Flow (cron schedule → InboxMessage)
   │                     TaskRequest (dept+skill routing → agent run)
   │                     A2ARequest (from_agent → to_agent → human approver → compiled report)
   │                     WorkJournalEntry
   │
   ├── Policy (scope: company | department | agent) + Department/AgentPolicyLink, PolicyConfig
   ├── ChangeRequest (dept-head → admin → Git commit)
   ├── DatabaseConnection (encrypted DSN for SQL query skills)
   ├── ProviderKey, GitConfig, TelegramConfig
   └── User ──< CompanyMember

Agentic OS: AuditEvent (hash chain) · AuditSeverity · GatewayUsage · PersonaTokenState ·
            RevokedToken · PersonaHeartbeat · PersonaCommand
```

---

## API Reference

- Swagger UI → `http://localhost:8000/docs`
- ReDoc → `http://localhost:8000/redoc`

Web UI endpoints use `Authorization: Bearer <user JWT>`; public ones are `/auth/token`,
`/auth/setup-status`, `/auth/setup`, `/auth/demo/*`, `/tenant/resolve`, `/system/version` and
`/.well-known/*`. Workstation endpoints (`/v1/*`, `/workstation/*`, `/audit/ingest`, `/mcp`) use
short-lived persona tokens issued by `3pa login`.

---

## Environment Variables

Set in `backend/.env` (dev) or the root `.env` (production, generated by `setup-env.sh`).

```bash
# Required — at least 32 chars; with ENVIRONMENT=production the app refuses
# to start on a placeholder or short value. Generate: openssl rand -hex 32
JWT_SECRET=

# Database — default sqlite:///./data/app.db; the compose files set PostgreSQL
DATABASE_URL=postgresql+psycopg2://agentic:<password>@db:5432/agentic
POSTGRES_PASSWORD=             # used by the compose files

# Runtime (optional)
ENVIRONMENT=development        # production in the prod/cloud compose files
APP_URL=http://localhost:5173  # invite links + default CORS origin
CORS_ORIGINS=                  # comma-separated; default APP_URL (+ localhost:5173 outside production)
SCHEDULER_ENABLED=true         # one worker runs cron flows / jobs via data/scheduler.lock

# Email (optional) — without it, invite tokens are printed to the log
RESEND_API_KEY=
EMAIL_FROM=noreply@yourdomain.com

# AI provider keys (optional) — imported once on first start; can also be added in Settings
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
MISTRAL_API_KEY=
QWEN_API_KEY=

# Agentic OS (optional)
PUBLIC_BASE_URL=               # public API base used in /.well-known documents
PERSONA_TOKEN_TTL_MINUTES=60
PERSONA_REFRESH_TTL_HOURS=12
```

Telegram, Git, social media, backup and database connections are configured per company from
**Settings**, not through environment variables.

---

## Testing

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v                     # SQLite; Postgres smoke tests are skipped
ruff check . && ruff format --check .

cd ../frontend && npm run check      # svelte-check
```

CI (`.github/workflows/`) runs lint, svelte-check and pytest on every PR, plus a real
PostgreSQL + pgvector job and separate suites for the gateway, policy engine, CLI, plugin and sandbox.

---

## TODO

### Security
- [x] CORS tightening — origins from `CORS_ORIGINS` / `APP_URL`, no credentialed wildcard
- [x] Invite role validation — `require_founder` guard on all user CRUD endpoints
- [x] A2A approver verification — `approver_id` stored and filtered per request

### Features
- [x] Onboarding session resume after browser close
- [x] Change request workflow for skills and policies — dept-approve → admin-approve → Git commit
- [x] A2A auto-compilation — orchestrator results compiled into executive report automatically
- [x] PostgreSQL support — PostgreSQL 16 + pgvector in all compose stacks, real-Postgres CI job
- [x] Telegram notifications — bot config in Settings, flow results + audit severity alerts
- [ ] WhatsApp task alerts — WhatsApp Cloud API is wired for agent skills, not yet for notifications
- [ ] Visual Flow Builder — drag-and-drop agent workflow designer with per-step model selection
- [ ] Agent Marketplace — ready-made templates (Legal Assistant, HR Agent, Finance Analyst) deployable in one click
- [ ] Timezone-aware datetimes in `models.py` (then lift the `sqlmodel<0.0.25` cap in `requirements.in`)

Agentic OS follow-ups are tracked per ADR in [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## License

**Commons Clause + MIT** — Free to use, fork, and self-host for your own organization. Selling, white-labeling, or offering this software as a hosted or managed service to third parties requires a commercial license.

Contact [bilgi@kuntaykunt.com](mailto:bilgi@kuntaykunt.com) for commercial licensing.

---

<sub>Built by [Fabrika Yazılım](https://fab.limited) · Istanbul · [bilgi@kuntaykunt.com](mailto:bilgi@kuntaykunt.com)</sub>
