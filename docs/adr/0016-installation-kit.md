# ADR-0016: Installation kit — org chart, identity, models, company systems

- **Status:** proposed
- **Date:** 2026-09-28
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0004, ADR-0007, ADR-0014, ADR-0015

## Context and problem

Rolling the platform out to a whole company (ADR-0014) is an installation
project, not a sign-up. Every company differs in four places, and all four must
be settled on the main server before people start working:

1. **Org chart** — companies, departments, roles, people, reporting lines.
2. **Identity** — how people sign in.
3. **Models** — which LLMs are used: cloud APIs or models the company runs itself.
4. **Company systems** — ERP, CRM, databases, file shares: agents need access
   through MCP, and the data work (mapping, cleaning, views) happens here too.

## Options considered

- **A — keep configuring each piece separately in Settings** (today's state).
- **B — a guided installation kit**: a server-side `setup` flow (CLI and web)
  that walks through the four steps in order, validates each one, and records the
  result as versioned configuration.

## Decision

**B.**

1. **Org chart.** Import from CSV / HRIS export, or build it with the existing
   AI onboarding. The result is the tree the TUI sidebar shows (ADR-0014).

2. **Identity — the installer picks one or more:**
   - username + password (existing JWT + bcrypt);
   - company SSO over **OIDC** (extends the existing `services/oidc.py`, today
     used only by `3pa login --oidc`, to web + TUI login);
   - **Google** sign-in (an OIDC provider with Google's issuer);
   - SAML 2.0 as a later addition for IdPs without OIDC.
   A signed-in identity maps to a `User` and a `Personnel` record by e-mail.

3. **Models — any OpenAI-compatible endpoint, defined by base URL + token.**
   A new generic provider type `openai_compatible` stores a **base URL**, an
   **API token** (encrypted like other keys) and the model list (fetched from
   `GET {base_url}/models` or entered by hand). This covers cloud APIs, vLLM,
   Ollama, LM Studio, LiteLLM and in-house gateways with the same code path. The
   named providers stay as presets. The installer validates the endpoint
   (`/models` + a one-token completion) before saving. The gateway (ADR-0004)
   routes to these endpoints unchanged. The ranking backend (ADR-0015: Jev or
   local) is chosen in the same step, with an explicit "documents may leave the
   premises" switch.

4. **Company systems — MCP per system, built during installation.**
   - A template for **read-only** MCP servers over a database / REST API
     (building on `DatabaseConnection` and the SQL query skills), plus a
     checklist for mapping ERP entities (customers, invoices, stock, orders).
   - Write actions are separate MCP tools that default to `ask` in the policy
     engine (ADR-0005) until the company approves them.
   - Each MCP server is registered per company and exposed to agents through the
     backend MCP server; every call is audited (ADR-0006).
   - Data work (views, cleaning, a reporting schema) is part of the installation
     deliverable and lives in the company's own repo / DB, not in this repo.

## Consequences

- **Positive:** A repeatable rollout. "Bring your own model" is a URL and a
  token. SSO and Google sign-in cover most companies. ERP access is uniform
  (MCP), audited and policy-gated.
- **Negative / cost:** ERP integration remains per-customer project work; the kit
  shortens it but cannot remove it. OIDC for the web and TUI needs a browser
  redirect flow (device-code flow for the TUI).
- **Accepted residual risk:** A misconfigured read-only MCP server can still
  expose more data than intended; the installer review step and the audit log are
  the controls.
- **Follow-ups:**
  1. `openai_compatible` provider type (backend + Settings UI + validation).
  2. OIDC login for web + TUI (auth-code + device-code), Google preset.
  3. `setup` flow skeleton that runs the four steps and stores a versioned config.
  4. Read-only MCP server template + ERP mapping checklist in `docs/`.
