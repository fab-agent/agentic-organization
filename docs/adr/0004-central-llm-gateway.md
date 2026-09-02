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
- **Streaming:** SSE passthrough; the gateway injects `stream_options.include_usage`
  when the client did not, tees the raw chunks through a line buffer, and reads
  the final `usage` chunk for the audit + quota counters.
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

## Implementation status (2026-09-02)

- `POST /v1/chat/completions` (stream + non-stream), `GET /v1/models`,
  `POST /policy/decide`, `GET /gateway/usage`.
- Upstream resolved from the company's active `ProviderKey` (`base_url` + key).
- Every call → the tamper-evident audit chain (ADR-0006).
- Guardrails in `services/gateway_limits.py`: model allow-list (comma globs,
  `gateway.model_allow[:company]`; the persona's own model is always allowed),
  per-persona rate limit (`gateway.rpm_limit`, in-process sliding window),
  daily/monthly token quota (`gateway.*_token_limit`, `GatewayUsage` table).
  `preflight()` before forwarding, `record_usage()` after. All default
  permissive.
- Streamed calls now meter tokens: `stream_options.include_usage` is injected
  when absent, and `_sse_usage()` pulls the `usage` object out of the SSE stream
  for `_audit_gateway_call` + `gateway_limits.record_usage` (`api/gateway.py`).
- Still open: a shared rate-limit + usage store (Redis) for multi-worker
  deployments; propagating a non-200 upstream status on the streaming path
  (today the client always sees 200, the real status is only in the audit).
