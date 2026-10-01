---
sidebar_position: 3
---

# Skill Types (Technical)

A `Skill` record carries a `skill_type` and a type-specific `config_json`. This page describes the real behavior of each type. For the business side see [Skills and Policies](/guide/skills-and-policies).

| Field | Description |
|---|---|
| `skill_type` | `builtin`, `mcp`, `http`, `function`, `database` |
| `config_json` | Type-specific setting (JSON text) |
| `is_active` | If `false`, it is left out of the tool list |
| `name` | The name the tool is called by |
| `description` | Description shown to the model |

## builtin

`config_json`: `{"function_name": "web_search"}`; if missing, `name` is used. Implemented tools:

| `function_name` | Status |
|---|---|
| `web_search` | Works: first 5 related topics from the DuckDuckGo Instant Answer API; no key needed |
| `journal_write` | Works: a Markdown entry in the session journal |
| `delegate_to_agent` | Works: opens an A2A request (`to_agent_slug`, `task`, `context`); if `to_agent_id` is written in the setting the target is fixed |
| `instagram_post`, `whatsapp_send` | Work: with the credentials in Settings → Social media |
| `text_to_chart` | **Placeholder:** returns text, does not produce a chart |
| `code_execution` | **Deferred:** does not execute |

## mcp

JSON-RPC 2.0 over HTTP. The platform sends `POST {url}/call` (as is if the url already ends with `/call`):

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "<skill.name>", "arguments": { }}}
```

Settings: `url`, `auth_type` (`none` · `api_key` → `X-API-Key` · `bearer`/`oauth2` → `Authorization: Bearer`), `auth_value`, optional `input_schema`. The first `text` content of the response is returned. Timeout 30 s. The stdio and SSE transports are not supported.

## http

Any REST address. Settings: `url`, `method` (`POST` default | `GET`), `headers`, optional `input_schema`. With `GET` the arguments become query parameters, with `POST` a JSON body. Timeout 30 s.

## function

Python code embedded in the record: `{"language": "python", "code": "def run(args):\n    return str(args)"}`. It must define `run(args: dict) -> str`. It must finish within **5 seconds**.

:::warning It is not a real sandbox
The code runs in a separate thread inside the server process, in a namespace restricted to **a few built-in functions** (`len`, `str`, `sum`, `json` …). This restriction does not provide full isolation and the timeout does not stop the thread. Let only people you trust write the function skill; such changes go through the change request flow.
:::

## database

Setting: `{"db_id": "<connection id>"}`. The agent generates SQL; the platform runs only `SELECT` / `WITH … SELECT` queries and rejects write commands. The schema and descriptions become context for the agent. See [Settings → Databases](/guide/settings#databases).
