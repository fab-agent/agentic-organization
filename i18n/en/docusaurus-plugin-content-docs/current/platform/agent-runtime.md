---
sidebar_position: 1
---

# Agent Runtime

This document explains how the agent execution engine works within the platform: session lifecycle, SSE streaming, multi-provider support, and the tool call loop.

---

## Session Lifecycle

Every conversation begins with an `AgentSession` record. Multiple messages can be exchanged within a single session; each message triggers the agentic loop.

```
POST /sessions                    → Create session
POST /sessions/{id}/messages      → Send message (returns SSE stream)
GET  /sessions/{id}               → Fetch session + message history
GET  /sessions                    → List sessions
DELETE /sessions/{id}             → Close session
```

When creating a session, `personnel_id` (a personnel record of agent type) is required:

```json
POST /sessions
{ "personnel_id": "uuid", "title": "Optional title" }
```

### Session States

| State | Meaning |
|---|---|
| `active` | Messages can be sent |
| `closed` | Session has ended, read-only |

---

## Sending Messages and SSE Streaming

When a message is sent, the backend responds with an SSE (Server-Sent Events) stream. The response uses HTTP's native streaming mechanism — not WebSocket.

```
POST /sessions/{session_id}/messages
Content-Type: application/json

{ "content": "Show me today's sales figures" }
```

Response: `Content-Type: text/event-stream`

Each event is delivered in the format `data: {json}\n\n`.

### SSE Event Types

| `type` | Description |
|---|---|
| `text` | Text chunk from the LLM |
| `tool_call` | The model invoked a tool |
| `tool_result` | Tool returned a result |
| `done` | Message complete, saved to DB with `message_id` |
| `error` | Runtime error |
| `stream_end` | Stream is closing (sent even on error) |

Example event sequence:

```
data: {"type":"text","content":"Sure, let me pull"}
data: {"type":"text","content":" those figures..."}
data: {"type":"tool_call","name":"web_search","args":{"query":"Q2 sales"}}
data: {"type":"tool_result","name":"web_search","result":"Q2 2026: 142K TL"}
data: {"type":"text","content":"Q2 sales came in at 142K TL."}
data: {"type":"done","message_id":"abc123"}
data: {"type":"stream_end"}
```

:::tip fetch + ReadableStream instead of EventSource
The `EventSource` API only supports GET requests. Because message content must be sent in a POST body, the frontend uses `fetch()` + `ReadableStream`.
:::

---

## Multi-Provider Support

The AI provider to use is automatically determined from the prefix of the `AgentConfig.model` field:

| Model Prefix | Provider | SDK |
|---|---|---|
| `gemini-*` | Google | `google-genai` v2.7 |
| `claude-*` | Anthropic | `anthropic` |
| `gpt-*`, `o1-*`, `o3-*` | OpenAI | planned |

```python
def detect_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("gemini"):            return "google"
    if m.startswith("claude"):            return "anthropic"
    if m.startswith(("gpt", "o1", "o3")): return "openai"
    return "google"  # default
```

The appropriate SDK adapter is activated for each provider; tool call formats (Gemini `FunctionDeclaration`, Anthropic `tools`, OpenAI `functions`) are converted automatically.

---

## Agentic Loop

A maximum of **8 iterations** run per message. In each iteration the model either produces text or calls a tool; if a tool is called, its result is appended as context for the next iteration.

```
User message
       │
   LLM call  (asyncio.to_thread)
       │
  ┌────┴────────────────┐
  │                     │
Text output       Tool call(s)
 → text event      → tool_call event
                         │
                  execute_skill()
                         │
                  tool_result event
                         │
                 Context updated
                 iteration < 8?
                  ├─ Yes → LLM call
                  └─ No  → done event
```

:::note asyncio.to_thread
Because the Google and Anthropic SDKs use synchronous calls, these calls are wrapped in `asyncio.to_thread` so the FastAPI event loop is not blocked.
:::

---

## System Prompt Structure

`build_system_prompt()` composes the agent's identity, department goals, and policies at the start of each message:

```
You are {person.name}.
Title: {person.title}
Department: {dept.name}

Department Goals:
{dept.goals}

Policies you must follow:
  - {policy_1}
  - ...

Available tools/skills: web_search, ...
```

Policies are embedded in the system prompt rather than in tool definitions; this keeps compatibility with all provider APIs and lets the model interpret rules through natural language understanding.

---

## DB Session Management

To avoid keeping a SQLite connection open during long-running LLM calls, a three-phase pattern is applied:

```python
# 1) Load data, save user message, CLOSE DB
with get_session() as session:
    ...
    session.commit()

# 2) LLM stream runs while DB is closed
async for event in agentic_loop():
    yield event

# 3) After stream finishes, save assistant message
with get_session() as session:
    session.add(asst_msg)
    session.commit()
```

---

## Built-in Tools (Builtin Skills)

Platform-native tools that require no external connectivity:

| Tool | Status | Description |
|---|---|---|
| `web_search` | Active | DuckDuckGo Instant Answer API |
| `text_to_chart` | Placeholder | Chart definition generation |
| `code_execution` | Deferred | Python sandbox |
| `delegate_to_agent` | Planned | A2A request creation |

---

## Related Documents

- [Agent Runtime Architecture (technical detail)](../architecture/runtime.md)
- [Skill Types](../architecture/skill-types.md)
- [Jobs Page — Usage](./chat-ui.md)
- [A2A Delegation](./a2a-delegation.md)
