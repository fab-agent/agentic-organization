---
sidebar_position: 1
---

# Installation

Three ways to run the platform: Docker (recommended), manual setup, or CLI wizard.

---

## Requirements

- Docker + Docker Compose **or** Python 3.11+ and Node.js 20+
- (Optional) AI provider API key: Anthropic / OpenAI / Google / Mistral

---

## Option A — Docker (Recommended)

```bash
git clone https://github.com/fab-agent/3rdparty-agent-org.git
cd 3rdparty-agent-org

cp .env.example .env
# Edit .env (AI keys are optional)

docker compose up --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |

---

## Option B — Manual Setup

**Backend:**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend (separate terminal):**

```bash
cd frontend
npm install
cp .env.example .env   # Set VITE_API_URL=http://localhost:8000
npm run dev            # http://localhost:5173
```

---

## Option C — CLI Wizard

```bash
cd packages/cli
npm install
npx 3pa init
```

The wizard guides you through:
1. Company name + industry
2. AI provider selection and API key entry
3. Git integration (optional)
4. Launch

---

## Environment Variables

Key variables in `.env`:

```bash
# AI Providers (optional — can also be added from Settings page)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
MISTRAL_API_KEY=...

# Frontend
VITE_API_URL=http://localhost:8000

# Security — CHANGE BEFORE PRODUCTION
JWT_SECRET=your-strong-random-secret

# First-run admin account
FOUNDER_EMAIL=admin@yourcompany.com
FOUNDER_PASSWORD=change-on-first-login
```

Generate a strong JWT secret:
```bash
openssl rand -hex 32
```

---

## First Launch

On first startup the platform seeds sample data:

- **Fabrika Yazılım** — 6 departments, 10 humans, 9 agents
- **Demo Corp** — 1 department, 3 people, 1 agent

Use this as a template or delete it. Log in with the `FOUNDER_EMAIL` / `FOUNDER_PASSWORD` you set.
