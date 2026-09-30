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
[`docs/adr/`](docs/adr/) (ADR-0001 … ADR-0021).

---

## Department Workspace (`fab`)

Non-developer departments work from a terminal client, `fab`, attached to a per-person
server-side workspace with one agent per person (ADR-0014, 0018–0021). It reuses the same gateway,
policy engine and audit chain.

| Component | Where |
|---|---|
| `fab` client (login, sidebar, agent pane, `fab workspace`, `fab sync`, "My review") | `packages/tui` |
| Workspace lifecycle API (behind a `WorkspaceRuntime` interface) | `backend/api/workspaces.py` |
| Prompt assembly with token budget, Jev intent classifier | `backend/services/context_assembly.py`, `intent.py` |
| Work review, fit rating, rubric, calibration, training-need signal | `backend/api/work_review.py`, `backend/services/` |
| Workspace image (LibreOffice, PDF tools, headless Chromium) | `sandbox/workspace/` |

**Not production-ready:** there is no real workspace runtime yet (only a test `FakeRuntime`), and fit
rating has not been measured against the live TypeSafe Jev API or reviewed legally, so work review,
rating, manager sharing and intent classification all ship **off per company**. Details, switches and
verification steps: https://agent-docs.fab.engineering/docs/fab/overview.

---

## Documentation

Product and platform guides (onboarding, A2A delegation, autonomous flows, change requests,
personnel portal, …) live on the docs site, not in this README: **https://agent-docs.fab.engineering**
(source: [fab-agent/docs](https://github.com/fab-agent/docs)). Architecture decisions stay here
in [`docs/adr/`](docs/adr/).

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

## Usage

After the first launch, follow the guides on the docs site: https://agent-docs.fab.engineering
(AI onboarding at **Settings → AI ile Kur** is the recommended first step).

---

## Architecture

| Path | What |
|---|---|
| `backend/` | FastAPI + SQLModel (PostgreSQL + pgvector; SQLite for dev): `api/`, `services/`, `models.py`, `migrations/`, `tests/` |
| `frontend/` | SvelteKit web UI (frozen for new product features, see ADR-0014) |
| `packages/cli` | `3pa` workstation CLI |
| `packages/agent-plugin` | opencode org plugin (policy, audit, taint tracking) |
| `packages/tui` | `fab`, the department terminal client (Rust + Ratatui) |
| `sandbox/` | Developer sandbox + egress proxy; `sandbox/workspace/` is the department workspace image |
| `docs/` | `ROADMAP.md`, `architecture/`, `adr/` |
| `.github/workflows/` | One path-scoped workflow per component, plus `adr-guard` |

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

# Department workspace / work review (optional; every feature here is off per company by default)
TYPESAFE_API_KEY=              # Jev: intent classification, fit rating, calibration (never commit)
WORKSPACE_RUNTIME=             # `fake` = tests only; no real runtime exists yet
PROMPT_BUDGET_TOKENS=2000
INTENT_TIMEOUT_SECONDS=1.5
INTENT_MIN_PROMPT_TOKENS=1500
WORK_REVIEW_MIN_GROUP=3        # smallest group shown in aggregates
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

## Roadmap

Status and next steps: [`docs/ROADMAP.md`](docs/ROADMAP.md). Open product ideas: WhatsApp task alerts,
visual flow builder, agent marketplace, timezone-aware datetimes in `models.py` (then lift the
`sqlmodel<0.0.25` cap).

---

## License

**Commons Clause + MIT** — Free to use, fork, and self-host for your own organization. Selling, white-labeling, or offering this software as a hosted or managed service to third parties requires a commercial license.

Contact [bilgi@kuntaykunt.com](mailto:bilgi@kuntaykunt.com) for commercial licensing.

---

<sub>Built by [Fabrika Yazılım](https://fab.limited) · Istanbul · [bilgi@kuntaykunt.com](mailto:bilgi@kuntaykunt.com)</sub>
