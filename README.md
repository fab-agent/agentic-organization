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
| AI provider key management (OpenAI, Mistral, Qwen, Ollama, LM Studio) | ✅ |
| **Autonomous Flows** — cron-scheduled agent tasks delivered to inbox | ✅ |
| **Task Requests** — route tasks to best-matched agent by dept + skill | ✅ |
| **Agent-to-Agent (A2A) delegation** with human approval + auto-compilation | ✅ |
| **Orchestrator agents** — Council Agent pattern with parallel specialist delegation | ✅ |
| **Token telemetry** — per-message token tracking across all providers | ✅ |
| **Long-term agent memory** — session summaries stored and injected into future context | ✅ |
| **Image generation in flows** — Qwen Image / DALL-E via DashScope task API | ✅ |
| Real-time AI chat sessions (SSE streaming) | ✅ |
| First-time setup wizard (no hardcoded credentials) | ✅ |
| JWT auth + bcrypt passwords + AES-256 key encryption | ✅ |
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
- Flows support all configured providers: OpenAI, Qwen, Mistral, Ollama, LM Studio
- Image generation flows route automatically to DashScope task API when an image model is detected
- Results land in the inbox and update flow telemetry (last run, status, output snippet)

---

## Quick Start

### Requirements

- Docker + Docker Compose **or** Python 3.11+ and Node.js 20+
- At least one active AI provider API key (OpenAI, Qwen, Mistral, or a local model via Ollama / LM Studio)

---

### Option A — Docker (Recommended)

```bash
git clone https://github.com/fab-agent/agentic-organization.git
cd agentic-organization

cp backend/.env.example backend/.env
# Edit .env — JWT_SECRET is required, AI provider keys are optional

docker compose up --build
```

UI → `http://localhost:5173`  
API → `http://localhost:8000`

**Production (with Nginx rate limiting):**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

UI + API → `http://localhost` (Nginx on port 80)  
Login endpoint is rate-limited to 5 attempts/minute per IP.

---

### Option B — Manual (Development)

**Backend:**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn main:app --port 8000
```

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

Update `VITE_API_URL` in `backend/.env` to `https://app.your-domain.com` before rebuilding.

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

Anyone in the org submits a task via `/tasks`. The system routes to the best-matched agent by department and skill filter.

### 11. Agent-to-Agent (A2A) Delegation

Configure **Council Agent** with specialist delegate skills. When given a task, it assigns sub-tasks to specialist agents (Lead Scout, Finance Copilot, CRM Steward, etc.). Humans approve each delegation. Results are automatically compiled into a final executive report.

View pending delegations under **Jobs → Delegasyon**.

### 12. AI Provider Management

Under **Settings → AI Sağlayıcılar**:

| Provider | Models |
|---|---|
| OpenAI (GPT) | gpt-4o, gpt-4o-mini, o3-mini |
| Mistral AI | mistral-large, mistral-small, codestral |
| Alibaba Qwen | qwen-max, qwen-plus, qwen-turbo, qwen-long, qwen-image-plus |
| Ollama (Local) | any model running locally |
| LM Studio (Local) | any model running locally |

Keys are stored encrypted with AES-256 (Fernet) — never returned as plain text.

### 13. Dashboard

The **Panel** page shows:
- **Company telemetry** (agent count, sessions, token usage, memory count)
- **Personal telemetry** (your agents' sessions, token consumption, long-term memory)
- **Agent SLA table** — per-agent sessions, tokens, flow success, A2A task completion rate

---

## Architecture

```
agentic-organization/
├── backend/                    # FastAPI + SQLModel (SQLite)
│   ├── main.py                 # App startup, router registration
│   ├── models.py               # SQLModel tables
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── database.py             # Engine + session
│   ├── api/
│   │   ├── auth.py             # Login, invite, setup wizard, JWT
│   │   ├── companies.py        # Company CRUD + stats
│   │   ├── departments.py      # Department CRUD + tree
│   │   ├── personnel.py        # Personnel + agent config + org-tree
│   │   ├── skills.py           # CompanySkill CRUD + AgentSkillLink assign/unassign
│   │   ├── policies.py         # Policy management
│   │   ├── onboarding.py       # AI Onboarding (search / chat / generate / create)
│   │   ├── sessions.py         # AI sessions + SSE streaming
│   │   ├── flows.py            # Autonomous flow scheduling (APScheduler)
│   │   ├── task_requests.py    # Task routing + human approval
│   │   ├── a2a.py              # Agent-to-Agent delegation + auto-compilation
│   │   ├── providers.py        # AI provider key management
│   │   ├── dashboard.py        # Live telemetry + SLA metrics
│   │   └── audit.py            # Audit log
│   ├── core/
│   │   └── security.py         # Fernet encryption (data/.secret)
│   ├── services/
│   │   ├── agent_runtime.py    # AI execution engine (multi-provider, token capture)
│   │   ├── memory_service.py   # Session summaries → AgentMemory (long-term memory)
│   │   ├── flow_runner.py      # Cron executor (qwen + image gen support)
│   │   ├── mcp_client.py       # Built-in skills + A2A delegation executor
│   │   ├── onboarding_agent.py # Web search + LLM conversation + bulk org creation
│   │   ├── provider_service.py # Provider testing + model listing
│   │   └── auth.py             # JWT + bcrypt helpers
│   └── migrations/             # Alembic migration scripts
│
└── frontend/                   # SvelteKit 5 + Tailwind
    └── src/
        ├── lib/
        │   ├── api/            # Type-safe fetch clients
        │   ├── components/ui/  # Bespoke UI components (Button, Dialog, Badge, Table...)
        │   ├── i18n/           # TR / EN translation dictionaries
        │   └── stores/         # authStore, companyStore
        └── routes/
            ├── setup/          # First-time setup wizard
            ├── onboarding/     # AI Onboarding wizard
            ├── agents/         # Agent list + config + skill assignment
            ├── skills/         # Company skills library + Markdown editor
            ├── policies/       # Policy management + Markdown editor
            ├── org-chart/      # Interactive org tree with agent detail panel
            ├── personnel/      # Personnel list + side panel
            ├── departments/    # Department management
            ├── flows/          # Autonomous flow management
            ├── tasks/          # Task request routing
            ├── a2a/            # Delegation queue + approval
            ├── change-requests/ # Two-step approval workflow
            └── settings/       # AI providers, Telegram, social media, backup
```

### Data Model

```
Company ──< Department ──< Personnel ──── AgentConfig ──< AgentSkillLink ──> CompanySkill
                                 │              │
                                 │         AgentSession ──< SessionMessage (tokens_used)
                                 │              │
                                 │         AgentMemory (long-term session summaries)
                                 │
                          Flow (cron schedule → InboxMessage)
                          TaskRequest (dept+skill routing → agent run)
                          A2ARequest (from_agent → to_agent → human approver → compiled report)
                          Policy (scope: company | department | agent)
                          DatabaseConnection (encrypted DSN for SQL query skills)
```

---

## API Reference

- Swagger UI → `http://localhost:8000/docs`
- ReDoc → `http://localhost:8000/redoc`

All endpoints require `Authorization: Bearer <token>` except `/auth/token`, `/auth/setup-status`, and `/auth/setup`.

---

## Environment Variables

```bash
# Required — at least 32 chars; with ENVIRONMENT=production the app refuses
# to start on a placeholder or short value
JWT_SECRET=<random-64-char-hex>

# Runtime (optional)
ENVIRONMENT=development        # production in the prod/cloud compose files
CORS_ORIGINS=                  # default: APP_URL (+ localhost:5173 outside production)
SCHEDULER_ENABLED=true         # one worker runs cron flows / jobs via data/scheduler.lock

# Telegram (for invite / notifications)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=

# AI Providers (optional — can also be added from Settings page)
OPENAI_API_KEY=sk-...
MISTRAL_API_KEY=...
QWEN_API_KEY=sk-...

# App URL (for invite links)
APP_URL=http://localhost:5173
```

---

## Testing

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

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
- [ ] Push Notifications UI — WhatsApp/Telegram task alerts (backend infra in place, frontend pending)
- [ ] Visual Flow Builder — drag-and-drop agent workflow designer with per-step model selection
- [ ] Agent Marketplace — ready-made templates (Legal Assistant, HR Agent, Finance Analyst) deployable in one click
- [ ] PostgreSQL support — swap SQLite for Postgres for concurrent workloads

---

## License

**Commons Clause + MIT** — Free to use, fork, and self-host for your own organization. Selling, white-labeling, or offering this software as a hosted or managed service to third parties requires a commercial license.

Contact [bilgi@kuntaykunt.com](mailto:bilgi@kuntaykunt.com) for commercial licensing.

---

<sub>Built by [Fabrika Yazılım](https://fab.limited) · Istanbul · [bilgi@kuntaykunt.com](mailto:bilgi@kuntaykunt.com)</sub>
