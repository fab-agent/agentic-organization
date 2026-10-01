---
sidebar_position: 2
---

# Installation

There are three ways: a local trial, a one-command production install, and a manual development setup. On the business side, the shortest path is to run the local trial first and follow [First Steps](/getting-started/first-steps).

## 1. Local trial (Docker)

```bash
git clone https://github.com/fab-agent/agentic-organization.git
cd agentic-organization
cp .env.example .env
# Set JWT_SECRET in .env (openssl rand -hex 32)
docker compose up --build
```

When it is ready:

- Interface: `http://localhost:5173`
- API: `http://localhost:8000` (interactive documentation: `/docs`)

This stack runs three services: PostgreSQL (pgvector), the backend and the interface.

## 2. Production install (one command)

On an Ubuntu server, with the DNS record ready:

```bash
git clone https://github.com/fab-agent/agentic-organization.git
cd agentic-organization
bash install.sh
```

`install.sh` does the following in order:

1. Checks Docker and Docker Compose.
2. Runs the `.env` wizard (`setup-env.sh`).
3. Obtains an SSL certificate with Let's Encrypt (Certbot).
4. Generates the Nginx configuration for your domain.
5. Starts the services (database, backend, interface, Nginx) with `docker-compose.prod.yml`.
6. Runs a health check.

The `.env` wizard can also be run on its own to generate only the environment variables: `bash setup-env.sh`. It asks for the domain, company details and optional provider keys; it generates `JWT_SECRET` itself.

## 3. Manual installation (development)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Interface (separate terminal)
cd frontend
npm install
cp .env.example .env     # VITE_API_URL=http://localhost:8000
npm run dev
```

If `DATABASE_URL` is not set, SQLite (`data/app.db`) is used.

## Environment variables

| Variable | Required? | Description |
|---|---|---|
| `JWT_SECRET` | Yes | Session signing key, at least 32 characters. A weak value is rejected in production. |
| `DATABASE_URL` | Automatic in Docker | SQLite by default; the compose files set PostgreSQL |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | In Docker | Database credentials |
| `APP_URL` | Recommended | Address used in invitation links |
| `CORS_ORIGINS` | Optional | Comma-separated allowed origins; default `APP_URL` |
| `RESEND_API_KEY`, `EMAIL_FROM` | Optional | Email delivery (Resend). If not set, emails are only written to the log. |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `MISTRAL_API_KEY`, `QWEN_API_KEY` | Optional | Imported once at first start; can also be added in Settings |
| `SCHEDULER_ENABLED` | Optional | The job scheduler that runs timed flows (on by default) |
| `PUBLIC_BASE_URL` | Optional | Public API address of the developer workstation layer |

`.env.example` and `setup-env.sh` also generate an `ENCRYPTION_KEY` variable, but the code does **not read** it. The encryption key lives in the automatically created `data/.secret` file; include this file in your backups.

Telegram, Git, social media, backup and database connections are set per company on the **Settings** page, not through environment variables.

## Obtaining the SSL certificate manually

`install.sh` does this automatically. If you want to do it yourself:

```bash
docker run --rm -v /etc/letsencrypt:/etc/letsencrypt -v /var/www/certbot:/var/www/certbot \
  -p 80:80 certbot/certbot certonly --standalone \
  --email admin@mycompany.com --agree-tos -d agents.mycompany.com

sed 's/__DOMAIN__/agents.mycompany.com/g' nginx.prod.conf.template > nginx.conf
docker compose -f docker-compose.prod.yml up -d
```

For renewal, add a weekly cron job: `certbot renew --quiet && docker exec <nginx-container> nginx -s reload`.

## First launch

If there are no users in the database, the application redirects you to the **setup page**. You enter your full name, company name, email and password (at least 8 characters); the account is created with the **founder** role and you are signed in automatically. This page only works while the database is empty. There is no fixed admin password.

Next step: [First Steps](/getting-started/first-steps).
