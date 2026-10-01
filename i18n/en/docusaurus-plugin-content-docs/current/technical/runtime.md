---
sidebar_position: 2
---

# Agent Runtime

This page describes what happens behind the scenes when you chat with an agent in the web interface.

## The path of a message

1. The client sends the message with `POST /sessions/{id}/messages`. The response is an **SSE** (server-sent events) stream; WebSocket is not used because the stream is one-way and works smoothly with standard HTTP.
2. The server saves the message, **closes** the database session (no connection is held during the long LLM stream), runs the stream, and saves the assistant message when it finishes.
3. When the session is closed, a **summary** is produced in the background and written to the agent's memory.

### SSE events

| Event | Meaning |
|---|---|
| `_meta` | Session and stream information |
| `text` | A piece of reply text |
| `tool_call` | The agent called a tool |
| `tool_result` | Tool result |
| `done` | Finished |
| `error` | Error |

## System prompt

For each turn the agent's instruction is assembled from named, **token-counted sections**: identity (name, role, department), company context, the person's job, rules, skills, policy names, the last **3 memory summaries** and **relevant knowledge** found by search. If the budget is exceeded, optional sections are dropped in a fixed order. Details and measurements: [fab → The person's agent and prompt](/fab/agent-and-context).

## Model routing

Which model is served from which address is decided by a single resolver (chat, flows, task requests and the gateway all use the same one):

1. If the agent has an **explicit provider**, that one; or a reference of the form `provider/model` (`ollama/llama3.1`).
2. A known model-name prefix (`claude-`, `gpt-`, `gemini`, `qwen`…).
3. An active local/custom address whose model list contains that model.
4. If none matches, Google.

The resolved provider must have an **active key**; there is no silent fallback to another provider's key. Anthropic and Google are spoken to with their own clients, the rest (OpenAI, Qwen, Mistral, Ollama, LM Studio, custom addresses) over the OpenAI protocol.

## Tool loop

If the model calls a tool, the server runs the tool, gives the result back to the model, and the loop continues until the model completes its reply (a limited number of turns). Every tool call first passes through the **policy engine** (`allow / ask / deny`); in the default mode (`dry_run`) the decision is only recorded, while in `enforce` mode `deny` and `ask` block the tool and a "[Policy denied: …]" message returns to the agent. Execution by skill type: [Skill Types](/technical/skill-types).

## Flows and task requests

Scheduled flows and task requests use the same model resolver and system prompt, but use their own runners rather than the chat loop. Tool calling in flows exists only for models using the Anthropic protocol ([Autonomous Flows](/guide/flows)).

## Memory and search

- **Memory:** the summary of a closed session (at least 2 messages) is stored as `AgentMemory`; in a new session the last 3 summaries enter the prompt.
- **Search (RAG):** with pgvector in PostgreSQL, session replies, task results and memories are embedded (incrementally every 15 minutes); relevant pieces (at most 4) are added to the prompt. Even if search fails, the session starts.
