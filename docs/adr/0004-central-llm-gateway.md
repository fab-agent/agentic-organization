# ADR-0004: Central LLM Gateway (OpenAI-compatible proxy, BYO upstream)

- **Status:** accepted
- **Date:** 2026-09-01
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0001, ADR-0003, ADR-0006, ADR-0007

## Context and problem

Developers and organisations want to route AI usage through **their own
OpenAI-compatible API endpoints** (a corporate AI gateway, LiteLLM, Azure OpenAI,
OpenRouter, local models). In addition:

- All prompt/response/token usage must be logged **independently of the client** —
  this is the hard backstop against the softness of laptop-side enforcement
  (ADR-0003).
- Per-persona quota / model allowlist / rate limit are needed.
- The backend already has `ProviderKey`, and it holds a `base_url` field.

## Options considered

- **A — each workstation calls the org's endpoint directly.** No central logging,
  no quota, the key on every laptop. Rejected.
- **B — a third-party gateway (LiteLLM etc.) as a separate service.** Powerful but
  a separate operational component, and the identity/audit integration has to be
  rebuilt on our side.
- **C — a thin OpenAI-compatible proxy in the backend** (`/v1/*`). Reuses the
  existing `ProviderKey` + audit + identity infrastructure; LiteLLM can still sit
  behind it if desired.

## Decision

**C.** Add `api/gateway.py` to the backend; OpenAI-compatible surface:

- `POST /v1/chat/completions` (priority), `POST /v1/embeddings`, `GET /v1/models`.
- **Identity:** a short-lived per-persona bearer token (ADR-0007) in the
  `Authorization` header. Separate from the web session JWT.
- **Upstream resolution:** request → persona → company → the company's active
  `ProviderKey` record (`base_url` + decrypted key). The organisation enters its
  own endpoint here.
- **Enforcement (only scaffolding in this ADR, details in ADR-0005):** model
  allowlist, per-persona daily/monthly token quota, rate limit.
- **Audit (ADR-0006):** for every call, `{persona, model, prompt_hash, token_in,
  token_out, latency, upstream_status}` is written to the audit chain. Raw
  prompt/response retention policy is configurable (default: retain, the company
  can turn it off).
- **Streaming:** SSE passthrough; token counting is finalized at the end of the
  stream.
- opencode side: in the managed config, a `provider` block with
  `@ai-sdk/openai-compatible` + `options.baseURL = https://<server>/v1` +
  `apiKey = {env:FABAGENT_TOKEN}`.

## Consequences

- **Positive:** Single-point visibility and control of model traffic, whatever the
  client does. The existing encrypted key store is reused. Keys never reach the
  laptops.
- **Negative / cost:** The backend is now a proxy on the critical path — latency
  and availability matter. The streaming proxy must be written carefully. The
  SQLite single-writer bottleneck may force Postgres as audit volume grows.
- **Accepted residual risk:** If the gateway is unreachable, the developer cannot
  work (deliberate — it prevents offline bypass, ADR-0003).
- **Follow-ups:** `api/gateway.py` skeleton; `gateway.yml` CI (OpenAI-compatible
  schema contract tests + audit assertion); Postgres migration plan.
