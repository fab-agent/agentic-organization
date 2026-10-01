---
sidebar_position: 2
---

# Central LLM Gateway

> ADR-0004 · `backend/api/gateway.py`, `backend/services/gateway_auth.py`,
> `backend/services/gateway_limits.py`

Agents on the workstation do **not** connect directly to the model provider. Instead they connect to the OpenAI-compatible proxy the platform provides. So authentication, quota, model restrictions, usage metering and the audit record all pass through a single point.

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completion (including streaming) |
| `GET`  | `/v1/models` | Models the persona can access |
| `POST` | `/policy/decide` | A policy decision for a tool call (used by the plugin) |
| `GET`  | `/gateway/usage` | The persona's current usage/quota state |
| `POST` | `/gateway/persona-token` | Generate a short-lived persona token (owner-scoped) |

The request arrives with an `Authorization: Bearer <persona-token>` header. Token validation is in `services/gateway_auth.py` (jose, HS256).

---

## BYO upstream

The gateway has no model key of its own. On every request the upstream is resolved from the company's `ProviderKey` record:

```
persona → company → ProviderKey(active)
                       ├── base_url   (e.g. https://api.anthropic.com/v1)
                       └── api_key    (encrypted with Fernet, decrypted and forwarded)
```

The right `ProviderKey` is chosen by the model prefix. Any OpenAI-compatible endpoint (Anthropic, OpenAI, Google, Mistral, Qwen, Ollama, LM Studio, self-hosted vLLM …) is supported.

---

## Streaming and usage metering

The SSE response is passed through from the upstream as it is (`_proxy_stream`). To capture the token consumption of streamed calls, `stream_options.include_usage = true` is injected into the request body; the last `usage` event that arrives (`_sse_usage`) is parsed and recorded into the `GatewayUsage` counters.

For non-streaming calls the `usage` field is read directly from the response.

---

## Guardrails

`services/gateway_limits.py`: all **permissive** by default, they take effect once explicitly configured:

| Restriction | How |
|---|---|
| Model allow-list | The list of allowed models for a persona/company; if the list is empty all are allowed |
| Rate limit | Requests per minute per persona |
| Token quota | Daily and monthly token ceiling (from the `GatewayUsage` table) |

When the quota is exceeded the request is rejected with `429`. `GET /gateway/usage` returns the current consumption and the remaining budget.

---

## Audit

Every gateway call is written to the audit chain as a `gateway_call` event through `record()` in `services/audit_chain.py` (model, token counts, persona, result). See [Audit Chain](./audit-chain.md).

---

## Open items

- A Redis-backed counter for rate limit / quota in multi-worker deployments (the Postgres advisory lock already covers PG).
- Behavior when the upstream returns a stream status other than 200.
