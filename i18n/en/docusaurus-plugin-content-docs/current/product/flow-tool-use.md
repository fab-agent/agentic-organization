---
sidebar_position: 14
---

# Tool Use in Flows

Scheduled flows are no longer limited to a single-turn LLM call. Flows running on **Anthropic** models can use the agent's defined skills as tools and complete multi-step tasks.

---

## How It Works

```
Flow triggered (cron)
    ↓
Agent's active skills loaded
    ↓
Skills converted to Anthropic tool definition format
    ↓
LLM called with tools parameter
    ↓
If LLM returns tool_use → tool is executed, result sent back to LLM
    ↓
(max 8 iterations)
    ↓
Final text response delivered to inbox
```

---

## Supported Skill Types

| Skill Type | Tool Use in Flows |
|---|---|
| `builtin` (web_search, text_to_chart) | ✅ Supported |
| `http` (if URL is defined) | ✅ Supported |
| `mcp` | ⚠️ Partial (in development) |
| `function` | ❌ Not yet supported |

---

## Provider Support

| Provider | Tool Use |
|---|---|
| **Anthropic (Claude)** | ✅ Full support (multi-turn tool loop) |
| OpenAI (GPT) | ⚠️ Single-turn fallback |
| Google (Gemini) | ⚠️ Single-turn fallback |
| Mistral | ⚠️ Single-turn fallback |

Tool use is only active for Anthropic models. Other providers continue to use single-turn mode.

---

## Iteration Limit

To prevent infinite loops, a flow run can make a **maximum of 8 tool calls**. When this limit is reached, the current response is returned.

---

## Example: Flow with Web Search

**Agent**: `market-analyst` — skill: `web_search (builtin)`

**Flow prompt**:
```
Research today's AI industry news and summarize the key developments.
```

**Execution steps**:
1. LLM calls `web_search`: `{"query": "AI news today"}`
2. DuckDuckGo search runs, result returned to LLM
3. LLM may call a second search or produce a summary
4. Final text lands in the inbox

---

## Skill Configuration

Skills used in flows must be **active** (`is_active: true`). Inactive skills are excluded from tool definitions.

Builtin skill `config_json`:
```json
{
  "function_name": "web_search"
}
```

HTTP skill `config_json`:
```json
{
  "url": "https://api.example.com/data",
  "method": "POST"
}
```
