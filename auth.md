# auth.md

`agent.fab.engineering` is the landing page for the open-source **Agentic
Organization** platform (<https://github.com/fab-agent/agentic-organization>,
MIT). The platform is self-hosted — every deployment is operated independently
and issues its own agent credentials. There is no shared, hosted API to register
against on this domain.

## Where the API lives

- Application API: `https://app.agent.fab.engineering` — OpenAPI at
  `/openapi.json`, agent card at `/.well-known/agent-card.json`.
- Agent tool interface: `POST https://app.agent.fab.engineering/mcp`
  (JSON-RPC 2.0, MCP protocol `2025-06-18`).

## Audience

External and laptop agents that need an organization's context — task
delegation, journal, registered-database queries, policy read-back.

## Registration / provisioning

No open self-service sign-up. An operator (the responsible human for a persona)
provisions access on their own deployment:

1. `GET /workstation/personas` — operator lists the agent personas they own.
2. `POST /workstation/persona-token` — operator mints a persona token for one
   persona and audience (`gateway` for the LLM gateway, `audit` for the MCP /
   tool-event surface).
3. `POST /workstation/persona-token/refresh` and `.../revoke` — rotate or revoke.

Tokens are short-lived JWTs bound to a persona, company and audience, with
server-side revocation.

## Using the credential

```
Authorization: Bearer <persona-token>
```

No cookie or query-parameter authentication is accepted.

## OAuth / OIDC

Standard OAuth2 metadata is not published — no shared authorization server. When
an operator enables OIDC, an external IdP token can be exchanged for a persona
token at `POST /workstation/oidc/exchange`; ask that operator for the issuer and
audience.

## Contact

Fabrika Yazılım Ticaret Limited Şirketi — bilgi@kuntaykunt.com
