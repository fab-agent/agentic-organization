---
sidebar_position: 12
---

# Settings

**Settings** (Executive and above) has six tabs: AI Providers, Git Integration, Backup, Databases, Integrations and Audit Log.

## AI Providers

This is where the models agents will use are connected. Keys are stored **encrypted** and are never shown again in plain text on screen.

**Cloud API services:** Anthropic, OpenAI, Google (Gemini), Mistral, Qwen (Alibaba DashScope). Enter the key and press **Save & Test**; the status appears as *Active*, *Invalid key* or *Not configured*.

**Local models:** Ollama and LM Studio. Enter the server address (Base URL); if the service is running the connection is tested automatically.

**Custom OpenAI-compatible addresses:** vLLM, LiteLLM, an in-house gateway or any OpenAI-compatible API. You enter a name, Base URL (`…/v1`), an optional token and (if the server does not support `/models`) a comma-separated list of models.

When a provider's key is added, its models become selectable when creating agents.

## Git Integration

Lets you version agent configurations and departments as YAML files in a Git repository. The same connection is used for committing [change requests](/guide/change-requests).

**Making the connection:** provider (GitHub, GitLab, Gitea), repository address (for example `https://github.com/company/ai-capabilities`), branch (default `main`) and an access token (`ghp_…` for GitHub, `glpat-…` for GitLab; write access to the repo is required). Optional: *open an automatic PR on push*.

**Synchronization:**

| Action | What it does |
|---|---|
| **Pull (Repo → DB)** | Imports the YAML files in the repository into the database |
| **Push (DB → Repo)** | Converts the database to YAML, commits and pushes (or opens a PR) |
| **Recent sync history** | Direction, status, file count, commit and message of each operation |

Repository layout:

```yaml
# agents/<slug>/agent.yaml
id: codeguard
name: CodeGuard
title: Code Review Agent
model: claude-sonnet-4-6
status: active
department: software-development
responsible: elif-yildiz
skills:
  - name: Code Review
    version: '2.1'
    description: PR review and security scan
```

Departments live under `departments/<slug>/department.yaml`.

:::caution Providers other than GitHub
The interface also offers GitLab and Gitea as choices and pull/push recognize them; however **change-request commits work only for GitHub**. Use GitHub in production.
:::

**Common problems:**

| Symptom | Likely cause |
|---|---|
| `401` | Token expired: create a new one |
| `403` | The token has no repo write permission |
| `404` | Wrong repository address |
| Commit fails | If the branch is protected, the bot/user needs permission to push directly |

## Backup

Backs up the database to S3-compatible storage (AWS S3, Cloudflare R2, MinIO). Information: endpoint (for R2/MinIO; empty for AWS S3), bucket, prefix (default `backups/`), region, access key and secret key (the secret key is stored encrypted). The **Backup Now** button takes an instant backup; the **Recent Backups** list shows file, size and date.

:::caution SQLite only
In-app backup currently backs up only the **SQLite** database file. Because Docker installations use PostgreSQL, this button does not work there. Back PostgreSQL up separately with `pg_dump` (or your provider's backup service) and also keep the **`data/.secret`** file; without it encrypted records cannot be decrypted.
:::

## Databases

A feature that lets agents query the company's real database for **reading**.

1. **Add Database**: name, type and connection string (DSN, stored encrypted).
2. **Discover**: tables, columns and row counts are read.
3. **Descriptions**: write meaningful descriptions for tables and columns and add **example queries**; the agent learns from them when it generates SQL. The better you describe, the more accurate the answers.
4. Assign a skill of type **Database** to an agent and pick this connection.

Security: only `SELECT` (and `WITH … SELECT`) queries are allowed; commands such as `INSERT`, `UPDATE`, `DELETE` and `DROP` are rejected. Still, it is recommended to define a **read-only database user** for the connection.

## Integrations

**Social media.** Instagram Business (user id + access token) and WhatsApp Business Cloud API (phone number id + token + default recipient). After saving the details, add the **Instagram post** or **WhatsApp message** skill to an agent. The post/message is made by an agent with the configured accounts; give these skills only to agents you trust.

**Telegram** (founder only). Create a bot with BotFather (`/newbot`), and enter the token and the chat id notifications will go to (found with `@userinfobot`). Telegram provides:

- **Notifications:** invitations and temporary passwords, flow results, audit alerts.
- **Interactive bot:** pick an agent with `/ajanlar` and chat by typing text, `/durum`, and approve/reject pending tasks and delegations with `/onaylar`.

The bot needs no webhook (the server polls Telegram regularly).

## Audit Log

The record of important actions (who did what to which record, and when). → [Dashboard → Audit log](/guide/dashboard#audit-log)
