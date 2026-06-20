---
sidebar_position: 3
---

# Agent Runtime Architecture

This document describes 3PA's agent execution layer: system prompt construction, tool definition pipeline, multi-provider routing, SSE stream design, and the agentic loop.

---

## Overview

When a user sends a message to an agent, the following steps are processed in order:

1. The `AgentSession` and associated `AgentConfig` + `Skill` records are loaded from the DB.
2. The system prompt and tool definitions are constructed.
3. The DB session is **closed** — no connection is held open during long-running LLM calls.
4. The appropriate adapter is selected based on the provider and the agentic loop begins.
5. SSE events (`text`, `tool_call`, `tool_result`, `done`) are sent as an HTTP stream.
6. After the loop ends, the assistant message is saved to the DB.

---

## System Prompt Construction

The `build_system_prompt()` function runs at the start of each message and assembles the agent's identity, context, and constraints as plain text.

```
You are {person.name}.
Title: {person.title}
Role: {person.role}
Department: {dept.name}

Department Goals:
{dept.goals}

Policies you must follow:
  - {policy_1}
  - {policy_2}

Available tools/skills: web_search, send_email

Respond helpfully and concisely. Use tools when they would help.
```

### Design Decisions

:::note Why are policies plain text in the system prompt?
Policies are short rule sets defined at the department level. Placing them in the system prompt rather than the `tools=[]` parameter provides two advantages: (1) Compatible with every LLM API — no provider-specific policy field required. (2) The model interprets the rules through natural language understanding, avoiding rigid parsing errors.
:::

:::note Why are tools in a separate `tools` parameter?
Because tools require structured invocation (`name`, `args`, `parameters` schema), each provider's built-in tool-calling mechanism is used. This ensures the model produces correct JSON and the platform can safely parse the tool_use/function_call stream.
:::

---

## Tool Definition Pipeline

`build_tool_definitions()` converts each active `Skill` record into a function declaration that can be sent to the provider.

```
Skill (DB)
  ├── skill_type: "builtin" | "mcp" | "http" | "function"
  ├── config_json: {...}
  └── is_active: true
          │
          ▼
  tool_def (dict)
  ├── name: "web_search"
  ├── description: "..."
  ├── parameters: {type: object, properties: {...}}
  ├── _skill_id: "uuid"
  ├── _skill_type: "builtin"
  └── _config: {function_name: "web_search"}
          │
          ▼ (for Google Gemini)
  types.FunctionDeclaration(
      name=..., description=...,
      parameters=types.Schema(...)
  )
```

The `_skill_id`, `_skill_type`, and `_config` fields are used solely for internal platform routing and are **not sent** to the LLM API.

---

## Multi-Provider Routing

The provider is determined by the prefix of the `AgentConfig.model` field.

| Model Prefix | Provider | SDK |
|---|---|---|
| `gemini-*` | Google | `google-genai` v2.7 (`from google import genai`) |
| `claude-*` | Anthropic | `anthropic` |
| `gpt-*`, `o1-*`, `o3-*` | OpenAI | (planned) |

:::note `model` vs `model_version` field
`AgentConfig.model_version` may be a short label like "4.6" and is insufficient for provider detection. Provider detection always uses the full `cfg.model` name (`gemini-2.0-flash`, `claude-sonnet-4-6`, etc.).
:::

```python
def detect_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("gemini"):   return "google"
    if m.startswith("claude"):   return "anthropic"
    if m.startswith(("gpt", "o1", "o3")): return "openai"
    return "google"  # default
```

---

## SSE Stream Design

### Endpoint

```
POST /sessions/{session_id}/messages
Content-Type: application/json
Accept: text/event-stream

{"content": "Show today's sales figures"}
```

Response: `Content-Type: text/event-stream`

### Why SSE Instead of WebSocket?

:::tip SSE selection rationale
The data stream the agent needs to deliver to the client is unidirectional (server → client). SSE is HTTP-native and has high compatibility with proxies and load balancers. The WebSocket handshake and binary framing protocol add unnecessary complexity for this use case. `fetch() + ReadableStream` is used instead of the EventSource API because EventSource does not support a POST body.
:::

### SSE Event Types

| `type` | Description | Example |
|---|---|---|
| `text` | Text chunk from the LLM | `{"type":"text","content":"Hello..."}` |
| `tool_call` | Model invoked a tool | `{"type":"tool_call","name":"web_search","args":{"query":"..."}}` |
| `tool_result` | Tool returned a result | `{"type":"tool_result","name":"web_search","result":"..."}` |
| `done` | Full message complete, saved to DB | `{"type":"done","message_id":"uuid"}` |
| `error` | Runtime error | `{"type":"error","message":"No active API key..."}` |
| `stream_end` | Stream closing (sent even on error) | `{"type":"stream_end"}` |

Each event is transmitted in `data: {json}\n\n` format.

### Frontend Integration

```typescript
const resp = await fetch(`/sessions/${sessionId}/messages`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ content: userInput }),
});

const reader = resp.body!.getReader();
const decoder = new TextDecoder();

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  const lines = decoder.decode(value).split("\n");
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const event = JSON.parse(line.slice(6));
    // event.type: "text" | "tool_call" | "tool_result" | "done" | "error" | "stream_end"
  }
}
```

---

## Agentic Loop

A maximum of **8 iterations** run per message. In each iteration the model either produces text or calls a tool; if a tool is called, the results are appended as context for the next iteration.

```
┌─────────────────────────────────────┐
│           User message              │
└──────────────┬──────────────────────┘
               │
        ┌──────▼──────┐
        │  LLM call   │  (asyncio.to_thread — synchronous SDK)
        └──────┬───────┘
               │
     ┌─────────┴──────────┐
     │                    │
  Text output        Tool call(s)
  → text event       → tool_call event
                         │
                  ┌──────▼──────┐
                  │ execute_skill│
                  └──────┬───────┘
                         │
                  tool_result event
                         │
               Context updated
               (iteration + 1)
                         │
              iteration < 8?
               ├── Yes → LLM call
               └── No  → done event
```

:::note Use of `asyncio.to_thread`
Google Gemini and Anthropic SDKs are currently used with synchronous `generate_content` / `messages.create` calls. These calls are wrapped in `asyncio.to_thread` to avoid blocking FastAPI's event loop. True character-level streaming is deferred to a future iteration.
:::

---

## DB Session Management

```python
# 1) Load data, save user message, CLOSE DB session
with get_session() as session:
    ...
    session.commit()

# 2) LLM streaming runs while DB session is closed (seconds to minutes)
async for event in gen:
    yield event

# 3) After streaming ends, open a new session and save the assistant message
with get_session() as session:
    session.add(asst_msg)
    session.commit()
```

This pattern is the most important architectural decision that prevents the SQLite connection from being held open during long-running LLM calls.

---

## MCP Transports

| Transport | Status | Notes |
|---|---|---|
| SSE / HTTP JSON-RPC | Supported | `call_mcp_sse_tool()` — JSON-RPC 2.0 POST to `/call` endpoint |
| HTTP direct | Supported | `call_http_tool()` — GET or POST, args passed as query/body |
| stdio | Deferred | Not yet supported as it requires process isolation |

MCP servers must expose a `/call` endpoint using the JSON-RPC 2.0 protocol:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": { "key": "value" }
  }
}
```

---

## Context Window Considerations

| Content | Where | Approximate Size |
|---|---|---|
| System prompt (identity + policies) | `system_instruction` | ~200–500 tokens |
| Tool definitions | `tools=[]` parameter | ~100–300 tokens / tool |
| Conversation history | `contents` list | All previous messages |
| Tool results | `function_response` parts | Varies by tool response |

Because policies are short rule sets, token consumption is low. Sessions with a large number of tools and a long history may approach the model's context limit; this will be managed with conversation summarization in a future release.

---

## Related Documents

- [Skill Types](./skill-types.md)
- [Provider Key Management](./provider-key-management.md)
- [A2A Architecture](../product/a2a-architecture.md)
