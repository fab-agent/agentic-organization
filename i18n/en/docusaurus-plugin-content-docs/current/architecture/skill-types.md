---
sidebar_position: 4
---

# Skill Types

This document describes the four skill types defined in 3PA, the `config_json` schema for each type, and their runtime behaviors.

---

## Overview

Each `Skill` record has the following fields:

| Field | Type | Description |
|---|---|---|
| `skill_type` | `string` | `builtin` \| `mcp` \| `http` \| `function` |
| `config_json` | `string` (JSON) | Type-specific connection/execution configuration |
| `is_active` | `boolean` | If `false`, the skill is excluded from the tool definition list |
| `name` | `string` | Identifier used to call the tool (spaces become `_`) |
| `version` | `string` | Semantic version (`1.0.0`) |
| `description` | `string` | Tool description shown to the LLM |

---

## builtin — Built-in Capabilities

Tools implemented within the platform that require no external connection.

### Supported Functions

| `function_name` | Description | Status |
|---|---|---|
| `web_search` | Web search via the DuckDuckGo search API | Active |
| `text_to_chart` | Convert data into a chart definition | Placeholder |
| `code_execution` | Execute Python code | Deferred |

### config_json Schema

```json
{
  "function_name": "web_search"
}
```

If `function_name` is not specified, `skill.name` is used.

### Parameter Schemas (Auto-generated)

`web_search`:
```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string", "description": "Search query" }
  },
  "required": ["query"]
}
```

`text_to_chart`:
```json
{
  "type": "object",
  "properties": {
    "data":       { "type": "string", "description": "Data as JSON or CSV string" },
    "chart_type": { "type": "string", "description": "bar, line, pie, etc." },
    "title":      { "type": "string" }
  },
  "required": ["data"]
}
```

`code_execution`:
```json
{
  "type": "object",
  "properties": {
    "code":     { "type": "string", "description": "Python code to execute" },
    "language": { "type": "string", "description": "Programming language" }
  },
  "required": ["code"]
}
```

### web_search Implementation

```
DuckDuckGo Instant Answer API
GET https://api.duckduckgo.com/?format=json&no_html=1&q={query}

RelatedTopics[0..4].Text fields are extracted from the response and returned line by line.
No API key required.
```

:::note text_to_chart and code_execution
`text_to_chart` currently returns a placeholder. `code_execution` is not yet active because it requires process isolation.
:::

---

## mcp — Model Context Protocol

A skill type that connects to external tool servers implementing the MCP standard via JSON-RPC 2.0 over HTTP.

### config_json Schema

```json
{
  "url":        "https://tools.example.com/mcp",
  "transport":  "http",
  "auth_type":  "api_key",
  "auth_value": "sk-..."
}
```

| Field | Required | Description |
|---|---|---|
| `url` | Yes | Base URL of the MCP server |
| `transport` | No | `"http"` (default) \| `"sse"` (planned) |
| `auth_type` | No | `"none"` \| `"api_key"` \| `"bearer"` \| `"oauth2"` |
| `auth_value` | Conditional | Required if `auth_type` is not `"none"` |
| `input_schema` | No | JSON Schema — if not specified, a single `input: string` parameter is used |

### Runtime Flow

```
platform → POST {url}/call
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "{skill.name}",
      "arguments": { ...model_args... }
    }
  }

MCP server response:
  {
    "result": {
      "content": [{ "type": "text", "text": "result text" }]
    }
  }
```

Authentication headers:

| `auth_type` | HTTP Header |
|---|---|
| `api_key` | `X-API-Key: {auth_value}` |
| `bearer` / `oauth2` | `Authorization: Bearer {auth_value}` |
| `none` | — |

:::note stdio support
MCP stdio transport is not currently supported as it requires process isolation. Only HTTP-based MCP servers can be used.
:::

---

## http — Direct HTTP Tools

A skill type that uses any REST endpoint as a tool. Does not require the MCP protocol.

### config_json Schema

```json
{
  "url":    "https://api.example.com/tool",
  "method": "POST",
  "headers": {
    "Authorization": "Bearer sk-...",
    "Content-Type":  "application/json"
  },
  "input_schema": {
    "type": "object",
    "properties": {
      "query": { "type": "string" }
    },
    "required": ["query"]
  }
}
```

| Field | Required | Description |
|---|---|---|
| `url` | Yes | Full URL of the tool endpoint |
| `method` | No | `"POST"` (default) \| `"GET"` |
| `headers` | No | Static HTTP headers (including authentication) |
| `input_schema` | No | JSON Schema — if not specified, a single `input: string` parameter is used |

### Runtime Behavior

- `GET`: Arguments are appended as query parameters.
- `POST`: Arguments are sent as a JSON body.
- If the response is JSON, it is parsed; otherwise it is returned as plain text.

---

## function — Python Function

A skill type where Agent-specific Python code can be defined directly within the record.

:::note Current status
Tool definition and DB record creation are supported for the `function` type, but **code execution is not yet active**. At runtime, the message `[Function execution deferred — {skill.name}]` is returned. A sandboxed execution environment will be added in a future release.
:::

### config_json Schema

```json
{
  "language": "python",
  "code": "def run(params):\n    return params['x'] * 2"
}
```

| Field | Description |
|---|---|
| `language` | Only `"python"` for now |
| `code` | Function definition to execute (must include the `run(params)` signature) |

### Parameter Schema (Auto-generated)

```json
{
  "type": "object",
  "properties": {
    "params": {
      "type": "string",
      "description": "JSON params string"
    }
  },
  "required": []
}
```

---

## Skill Selection Guide

| Need | Recommended Type |
|---|---|
| Web search, chart generation, code execution | `builtin` |
| External tool server following the MCP standard | `mcp` |
| Custom REST API or webhook | `http` |
| Agent-specific logic (short Python) | `function` |

---

## Related Documents

- [Agent Runtime Architecture](./runtime.md)
- [Policy & Skills (Product)](../product/policy-and-skills.md)
