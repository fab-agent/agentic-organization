# Agentic Organization

Self-hosted, open-source platform for companies to manage AI agents as first-class members of their org chart.

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
| AI provider key management (Anthropic, OpenAI, Google, Mistral, Qwen) | ✅ |
| **Autonomous Flows** — cron-scheduled agent tasks delivered to inbox | ✅ |
| **Task Requests** — route tasks to best-matched agent by dept + skill | ✅ |
| **Agent-to-Agent (A2A) delegation** with human approval | ✅ |
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
| Live dashboard — company + personal telemetry (tokens, sessions, memories) | ✅ |

---

## AI Onboarding

The standout feature. Instead of manually setting up departments, agents, skills and policies one by one, a conversational AI assistant does it for you:

1. **Web Search** — the system automatically researches your company online for context
2. **Guided Chat** — the AI asks 3–5 targeted questions about your team size, recurring workflows, tools used, and data sensitivity constraints
3. **Preview** — a complete org structure is generated and shown before anything is written to the database
4. **One-click Create** — departments, human personnel, AI agents, skills (with full Markdown content), and policies are all created in a single transaction

To start: **Settings → AI ile Kur** (requires at least one active AI provider key).

---

## Autonomous Flows

Cron-scheduled agent tasks that run independently and deliver results to the responsible user's inbox.

- Any agent can have one or more flows (e.g., every 15 min, every 30 min)
- Flows support all providers: Anthropic, OpenAI, Qwen, Mistral, Google
- Image generation flows route automatically to DashScope task API when an image model is detected
- Results land in the inbox and update flow telemetry (last run, status, output snippet)

---

## Quick Start

### Requirements

- Docker + Docker Compose **or** Python 3.11+ and Node.js 20+
- (Optional) AI provider API key: Anthropic / OpenAI / Google / Mistral / Qwen

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
pip install -r requirements.txt
uvicorn main:app --port 8000
```

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

Create policies scoped to **company**, **department**, or **agent** with a full Markdown editor. Policies created during AI Onboarding appear here automatically.

### 8. Org Chart

The **Org Chart** page shows the full personnel hierarchy as an interactive tree. Click any agent node to open a detail panel with model, status, assigned skills, and linked policies.

### 9. Autonomous Flows

Under **Personnel → [Agent] → Flows**: create cron schedules (e.g., `*/15 * * * *`) with a prompt. The agent runs automatically and delivers results to the responsible human's inbox.

### 10. Task Requests

Anyone in the org submits a task via `/task-requests`. The system routes to the best-matched agent by department and skill filter. The responsible human approves execution via `/task-requests/{id}/run`.

### 11. Agent-to-Agent (A2A) Delegation

An agent requests a task from another agent. A designated human must approve before execution and again after reviewing the result.

Flow: `create → pending_approval → approved → running → pending_result_approval → completed`

### 12. AI Provider Management

Under **Settings → AI Providers**:

| Provider | Models |
|---|---|
| Anthropic (Claude) | claude-opus-4-8, claude-sonnet-4-6, claude-haiku-4-5 |
| OpenAI (GPT) | gpt-4o, gpt-4o-mini, o1, o3-mini |
| Google (Gemini) | gemini-2.5-pro, gemini-2.0-flash |
| Mistral | mistral-large, mistral-small, codestral |
| Alibaba Qwen | qwen-max, qwen-plus, qwen-turbo, qwen-long, qwen-image-plus |

Keys are stored encrypted with AES-256 (Fernet) — never returned as plain text.

### 13. Dashboard

**Göstergeler** shows live company telemetry (agent count, sessions, token usage, memory count) and personal telemetry for the logged-in user (their agents' sessions, token consumption, long-term memory summaries).

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
│   │   ├── policies.py         # Policy CRUD
│   │   ├── onboarding.py       # AI Onboarding (search / chat / generate / create)
│   │   ├── sessions.py         # AI sessions + SSE streaming
│   │   ├── flows.py            # Autonomous flow scheduling (APScheduler)
│   │   ├── task_requests.py    # Task routing + human approval
│   │   ├── a2a.py              # Agent-to-Agent delegation flow
│   │   ├── providers.py        # AI provider key management
│   │   ├── dashboard.py        # Live telemetry + personal stats
│   │   └── audit.py            # Audit log
│   ├── core/
│   │   └── security.py         # Fernet encryption (data/.secret)
│   ├── services/
│   │   ├── agent_runtime.py    # AI execution engine (multi-provider, token capture)
│   │   ├── memory_service.py   # Session summaries → AgentMemory (long-term memory)
│   │   ├── flow_runner.py      # Cron executor (qwen + image gen support)
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
            └── settings/       # AI providers, Telegram, social media, backup, flows
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
                          TaskRequest (dept+skill routing → human approval → agent run)
                          A2ARequest (from_agent → to_agent, human approver)
                          Policy (scope: company | department | agent)
```

---

## API Reference

- Swagger UI → `http://localhost:8000/docs`
- ReDoc → `http://localhost:8000/redoc`

All endpoints require `Authorization: Bearer <token>` except `/auth/token`, `/auth/setup-status`, and `/auth/setup`.

---

## Environment Variables

```bash
# Required
JWT_SECRET=<random-64-char-hex>

# Telegram (for invite / notifications — replaces email)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=

# AI Providers (optional — can also be added from Settings page)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
MISTRAL_API_KEY=...
QWEN_API_KEY=sk-...

# App URL (for invite links)
APP_URL=http://localhost:5173
```

---

## Testing

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

---

## TODO

### Security
- [ ] CORS tightening — `allow_origins=["*"]` should be restricted in production
- [x] Invite role validation — `require_founder` guard on all user CRUD endpoints
- [x] A2A approver verification — `approver_id` stored and filtered per request

### Features
- [x] Onboarding session resume after browser close — `save_onboarding_session` / `get_onboarding_session` implemented
- [x] Change request workflow for skills and policies — `propose=true` flag on skill/policy update endpoints; full dept-approve → admin-approve flow in `api/change_requests.py`
- [ ] Push Notifications UI — WhatsApp/Telegram task alerts (backend infra in place, frontend pending)
- [ ] Visual Flow Builder — drag-and-drop agent workflow designer with per-step model selection
- [ ] Agent Marketplace — ready-made templates (Legal Assistant, HR Agent, Finance Analyst) deployable in one click
- [ ] PostgreSQL support — swap SQLite for Postgres for concurrent workloads

---

## License

**MIT + Commons Clause** — Free to use, fork, and self-host for your own organization. Reselling, white-labeling, or offering as a paid service requires a commercial license. Contact [bilgi@kuntaykunt.com](mailto:bilgi@kuntaykunt.com) to discuss.

---

<sub>Built by [Fabrika Yazılım](https://fab.limited) · Istanbul · [bilgi@kuntaykunt.com](mailto:bilgi@kuntaykunt.com)</sub>
