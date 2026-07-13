---
sidebar_position: 0
---

# Changelog

A chronological record of platform updates.

---

## v0.9 — July 12, 2026

### Token Telemetry and Memory Fixes

#### Token Tracking Fix
- In `_stream_openai_compatible` and `_stream_anthropic`, token counts were being reset on each tool-use loop iteration; they are now accumulated across all iterations and sent in a single `_meta` event.
- `SessionMessage.tokens_used` is now correctly recorded for all providers including Qwen.
- Added a `prompt_tokens + completion_tokens` fallback calculation for cases where `total_tokens` is missing in Qwen `resp.usage`.

#### Dashboard/Me Fix
- The `/dashboard/me` endpoint was querying sessions by the user's own `personnel_id` (always returning 0 results). It now queries sessions for agents the user is responsible for; if no responsible agent exists, falls back to all company agents.
- `/dashboard/stats` now correctly aggregates company-wide token and memory data.

#### Long-Term Memory — Qwen Support
- `memory_service.py`: Added `_prov_for_model()` helper and Qwen provider fallback; Qwen agents now create `agentmemory` records when sessions are closed.
- `_call_summary_llm()`: Added OpenAI-compatible client branch for Qwen/Mistral; `base_url` is now dynamically read from the `ProviderKey` table.

---

### Flow Runner Improvements

#### Qwen Image Generation in Flows
- `flow_runner.py`: Added `is_image_gen_model()` detection; flows triggered by `qwen-image-*`, `wanx-*`, `flux-*` model names are automatically routed to the DashScope task API.
- `_generate_image_sync()`: DashScope async task API (submit + poll) implemented with httpx to work within the synchronous flow runner; delivers results as a Markdown image to the inbox with an 80-second timeout.
- `_call_llm()`: Added OpenAI-compatible branch for Qwen/Mistral.

#### Task Routing Fix
- `task_requests.py`: `_route_agent()` was only checking the legacy `Skill` table. It now also queries the `AgentSkillLink/CompanySkill` table, searching for skill matches in both structures.
- Added `_model_to_provider()` helper; the task runner now automatically derives the provider from the agent model (including Qwen).

---

### Integration Tests

#### GitHub Integration
- `fab-agent/fabrika-yazilim-org` repository connected and verified with existing token.

#### Telegram
- Bot integration verified; notifications active.

#### PostgreSQL — Odoo-Compatible Database
- PostgreSQL 18 database compatible with Odoo MRP 2 schema added to the system.
- DSN: `postgresql://odoo_agent:***@127.0.0.1:5432/fabrika_odoo`
- Tables: `mrp_production`, `mrp_bom`, `mrp_bom_line`, `mrp_workorder`, `product_template`, `product_product`
- pg_hba.conf md5 authentication configured.

#### Autonomous Flows
- APScheduler-based flows tested and verified with `*/15` and `*/30` cron schedules.

---

## v0.8 — July 9, 2026

### Features

#### AI Onboarding
- **Set Up with AI** button added under Settings → AI Providers (only visible for companies that haven't been onboarded yet).
- Clicking it opens a full-screen `/onboarding` page without sidebar/topnav.
- **Phase 1 — Research:** DuckDuckGo company web research is performed; results are passed to the onboarding AI context.
- **Phase 2 — Conversation:** AI asks 3–5 questions in English (team size, departments, priority processes). As the user answers, the structure becomes clearer; AI sends a `<READY_TO_GENERATE/>` signal when ready.
- **Phase 3 — Preview:** Number of departments, people, agents, skills, and policies to be created is shown with cards + collapsible sections. "← Back to Chat" allows revision.
- **Phase 4 — Create:** All entities are written to the database in a single click (FK order: department → skill → person → agent+AgentConfig+skill link → policy). The `ai_onboarded` flag is set to `true`; user is redirected to the main app.
- New backend service: `services/onboarding_agent.py` — DDG search, multi-turn LLM conversation (SSE stream), structured JSON generation, bulk entity creation.
- New API module: `api/onboarding.py` — 5 endpoints (`/onboarding/status/{id}`, `/search`, `/chat`, `/generate`, `/create`).
- `ai_onboarded: bool` field added to `Company` model + Alembic migration.
- `ddgs>=6.0` dependency added to `requirements.txt`.

#### Skills & Policies Pages (v0.7)
- `/skills` page: YapiTabs + skill card grid, 3-mode side panel (view/edit/create), Markdown editor (Write/Preview tabs), CR approval flow.
- `/policies` page: scope filter pills (All/Company/Department/Agent), same Markdown editor and CR flow.

#### Sidebar Restructure (v0.7)
- Departments/People/Agents/Skills/Policies nav items removed; replaced with two top-level items: **Dashboard** (dashboard) and **Structure** (all structure pages).
- `YapiTabs` component provides tab navigation on every structure page.

---

## v0.6 — July 9, 2026

### Features

#### Live Dashboard & AI Telemetry
- Dashboard completely rewritten: company-specific real-time metrics (headcount, agent count, active agents, today's/total sessions, token usage, memory record count).
- User-specific section: users linked to a personnel record see their own sessions, token usage, and long-term memory summaries directly on the dashboard.
- New backend endpoints: `GET /dashboard/stats` (company telemetry) and `GET /dashboard/me` (user telemetry).
- `/auth/me` response now includes `personnel_id` for each company membership.

#### Company Information Panel (company.md)
- A gear icon was added next to the company name in the navbar; clicking it opens a right side panel showing vision, mission, values, and goals.
- Admin and above roles can edit; regular users see read-only view.
- The old company.md card widget on the dashboard was removed.

#### Personnel Side Panel
- Right panel opening on row click for human personnel: info (department, manager, email, platform status), recent sessions, long-term memory summaries.
- Panel has 3 modes: `view` (info display) → `edit` (editing form within panel, back arrow returns to view) → `create` (new personnel).
- Personnel create/edit popup dialog removed entirely.

#### Agent Memory Viewing
- New backend endpoint: `GET /sessions/memories?personnel_id=...` — returns AI-generated summaries from closed sessions.
- Session list and memory summaries visible in the personnel side panel and user dashboard.

#### Telegram Notification Integration
- Resend email integration completely removed; invitation and password reset notifications are now delivered via Telegram Bot API.
- **Settings → Integrations** tab: bot token and admin chat ID configuration, test message sending, bot info display.
- Bot token stored encrypted with AES-256; `TelegramConfig` table added via Alembic migration.

#### AI Providers Tab Redesign
- Settings → Providers: only providers with keys entered are shown; unconfigured ones are added via an "Add Provider" dropdown flow.
- Old records in invalid state were cleaned up.

### UI Improvements

- **Settings tabs scrollable:** 6 tabs accessible via horizontal scroll on small screens; scrollbar hidden.
- **Sidebar collapse:** On desktop, sidebar toggles between `w-60` and `w-16`; icons visible, labels hidden.
- **Company selector moved to navbar:** Large company card at the bottom of the sidebar removed; added as a compact dropdown in the navbar.
- **Right panel overlay:** Side panel on agent and personnel pages overlays content rather than pushing it (`position: fixed`).

---

## v0.5 — July 9, 2026

### Security

#### Company-Level Authorization
- All API endpoints (`companies`, `departments`, `personnel`, `org-tree`, `sessions`) now verify the JWT holder's membership in the relevant company.
- A user can be a member of multiple companies; list endpoints return only data from companies the user has access to.
- `check_company_membership()` and `_get_person_and_check_membership()` helper functions added.

#### Pydantic Validation
- Auth endpoints (`login`, `setup`, `change-password`, `invite`) now use strongly typed Pydantic schemas instead of `body: dict`.
- Email normalization and minimum password length (8 characters) validation enforced at the schema level.

#### SSE Session Cleanup
- When Server-Sent Events (SSE) connections are dropped, session status transitions from `active` to `idle`; no longer left hanging.

#### Password Change Requirement
- Invited users are redirected to `/set-password` on first login; this page cannot be skipped.

### Infrastructure

#### Database Migrations (Alembic)
- Alembic integration completed; schema changes can now be tracked with `alembic revision --autogenerate`.
- `render_as_batch=True` enabled for SQLite `ALTER TABLE` support.

#### Structured JSON Logging
- JSON-format logging to `logs/app.log`; automatic 30-day rotation.
- HTTP request/response logging middleware added (method, path, status, ms).

#### Nginx Rate Limiting
- `docker-compose.prod.yml` + `nginx.conf` for production: login endpoint 5 requests per minute per IP, general API 60 requests.

#### Cloudflare Tunnel
- Cloudflare Tunnel guide for HTTPS setup added to README (Option C).

### Features

#### S3/R2/MinIO Backup
- **Settings → Backup** tab: S3, Cloudflare R2, or MinIO-compatible storage configuration.
- Safe online backup via `sqlite3.backup()` API, upload via boto3.
- Backup history (last 20 backups), one-click backup button, credentials stored encrypted.

#### Social Media Agent Skills
- `instagram_post` built-in skill: photo publishing to Instagram Business accounts via Graph API v21.0.
- `whatsapp_send` built-in skill: text message sending via WhatsApp Business Cloud API.
- **Settings → Social Media** tab: IG User ID + Access Token, WA Phone Number ID + Access Token configuration; credentials stored encrypted with AES-256.
- Any agent can post to social media by adding these skills as built-in in agent configuration.

---

## v0.4 — July 2, 2026

### New Features

#### Alibaba Qwen Integration
- Alibaba Qwen (DashScope) added to **Settings → AI Providers**.
- Supported models: `qwen-max`, `qwen-plus`, `qwen-turbo`, `qwen-long`
- Works via DashScope's OpenAI-compatible API; full tool-use support in agent runtime.

#### First-Time Setup Wizard
- When setting up the system for the first time, a **setup form** is shown instead of a fixed admin password (n8n-style).
- Form fields: Full Name, Company Name, Email, Password, Confirm Password.
- On form submission, the first user is created with the `founder` role and automatically logged in.
- The `/setup` page is disabled (403) when a user already exists in the DB.

### Improvements
- Frontend language options limited to Turkish and English (German and Spanish removed).

---

## v0.3 — June 23, 2026

### New Features

#### Audit Log — Full Coverage
- `log_action()` calls added for all mutation API endpoints (`companies`, `departments`, `personnel`, `providers`, `flows`, `change_requests`, `git_sync`).
- Every create, update, and delete operation is recorded with user ID, company ID, and operation details.
- Audit log page: **Settings → Audit Log**.

---

## v0.2 — June 19, 2026

### New Features

#### Agent Memory
- Persistent memory support added across agent sessions.
- `MemoryStore` model: key-value pairs, TTL, company and agent-scoped.

#### Flow Tool Use
- Autonomous flows now support tool calls.
- Tool results are saved to flow history.

#### Multi-Language Interface
- All pages wrapped with `t()` translation function.
- Supported languages: Turkish, English.

---

## v0.1 — June 1, 2026

### Initial Release (Phase 1 + Phase 2)

#### Core Platform
- Company and department management (CRUD).
- People and agent management.
- Organization chart visualization.
- User roles and invitation system (founder, executive, dept_head, agent_owner, user).
- JWT-based authentication.

#### AI Infrastructure
- Provider key management: Anthropic, OpenAI, Google Gemini, Mistral.
- Agent runtime: tool calls, skill system, session history.
- MCP (Model Context Protocol) tool support.

#### Integrations
- GitHub / GitLab / Gitea integration (markdown file synchronization).
- Email-based invitation system via Resend.
- A2A (Agent-to-Agent) delegation protocol.

#### Interface
- SvelteKit 5 + Svelte runes architecture.
- Custom shadcn/ui-inspired component library.
- Multi-company support; sidebar company switcher.
- Dark / Light theme.
