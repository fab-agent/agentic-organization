---
sidebar_position: 1
---

# Requirements

This page is for IT staff. Before installing, make sure your server meets the following.

## Server

| | Minimum | Recommended |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU |
| Memory | 4 GB | 8 GB |
| Disk | 20 GB SSD | 50 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |

The platform does **not** run an AI model; it connects to external providers (or to your own local model server). No GPU is needed.

## Software

**Docker installation (recommended):**

| Software | Version |
|---|---|
| Docker Engine | 24.0+ |
| Docker Compose | v2.20+ |
| `openssl` or `python3` | either one (to generate secrets) |

**Manual (development) installation:** Python 3.11+, Node.js 20+, and PostgreSQL 16 with the pgvector extension, or SQLite for a local trial.

## Database

Docker installations ship with **PostgreSQL 16 + pgvector** (the `pgvector/pgvector:pg16` image); you do not need to install anything separately. pgvector powers semantic search over agent memory and past sessions.

SQLite is for local development only (it is used when `DATABASE_URL` is not set).

:::caution Backups
The in-app backup in Settings currently backs up only the SQLite file. If you use PostgreSQL (the default of the Docker setup), back up the database separately with `pg_dump`. Details: [Settings → Backup](/guide/settings#backup).
:::

## Network and domain

| Port | Use |
|---|---|
| 80 | HTTP (certificate validation and redirect to HTTPS) |
| 443 | HTTPS |

In production only 80, 443 and SSH should be open to the outside. In development the backend listens on `8000` and the interface on `5173`, bound to `localhost` only.

Production needs a domain or subdomain (for example `agents.mycompany.com`). The DNS A record must point to your server's IP **before** installation; propagation can take 5 minutes to 48 hours (check with `nslookup agents.mycompany.com`). `install.sh` obtains a Let's Encrypt certificate for a single domain.

If you want to give each company its own subdomain (`company.agent.mycompany.com`), you need a multi-tenant setup; see [Architecture → Multi-tenant subdomains](/technical/architecture#multi-tenant-subdomains).

## AI providers

During installation or later, add at least one provider under **Settings → AI Providers**. [AI Setup](/guide/onboarding) and agent chats need this key.

| Provider | Note |
|---|---|
| Anthropic, OpenAI, Google, Mistral, Qwen (Alibaba) | Cloud API; a key is required |
| Ollama, LM Studio | Local models running on your own server; you enter the address |
| Custom OpenAI-compatible address | Such as vLLM, LiteLLM or an in-house gateway; address + optional token |

## Security notes

- `JWT_SECRET` (session signing) must be at least 32 characters; `setup-env.sh` generates it automatically.
- Stored provider keys, tokens and database connection strings are encrypted with a **Fernet key**. The key is written to `data/.secret` on first run (permission `600`). If you lose this file, encrypted records cannot be decrypted: store it **together with** the database backup.
- With `ENVIRONMENT=production`, the application **refuses to start** with a placeholder or short `JWT_SECRET`.
- No outside access to the data directory or the database port.
- Nginx applies rate limiting to the login page.
