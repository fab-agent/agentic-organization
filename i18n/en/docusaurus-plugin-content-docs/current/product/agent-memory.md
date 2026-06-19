---
sidebar_position: 13
---

# Agent Memory

Agents are stateless by default — each chat session starts fresh. **Agent Memory** automatically generates summaries from closed sessions and injects them into the system prompt of the next session.

---

## How It Works

```
Session is closed
    ↓
Background task is triggered
    ↓
LLM summarizes the conversation (max 100 words)
    ↓
Summary stored in AgentMemory table
    ↓
New session is opened
    ↓
Last 3 summaries injected into system prompt
```

---

## Summary Generation

When a session is closed (`DELETE /sessions/{id}`), a background LLM call runs automatically:

- The last 30 messages of the conversation are taken
- The LLM produces a short summary starting with: *"In a previous session, ..."*
- The summary is written to the `AgentMemory` table
- A failed summary never prevents the session from closing

---

## System Prompt Injection

When a new chat session starts, the agent's last 3 memories are appended to the system prompt:

```
Context from your previous sessions:
  - In a previous session, the user asked about the Q1 budget report.
    The agent completed the analysis and delivered a summary to the inbox.
  - In a previous session, the agent helped onboard a new team member
    named Elif by explaining department policies.
```

---

## Configuration

Memory injection is currently automatic for all agents. The only requirement: at least one active AI provider key must be configured on the platform.

| Parameter | Value |
|---|---|
| Max messages summarized | 30 |
| Previous sessions injected | 3 |
| Max summary length | ~100 words |

---

## Data Model

```sql
AgentMemory
  id           UUID primary key
  personnel_id UUID → Personnel
  session_id   UUID → AgentSession (nullable)
  summary      TEXT
  created_at   DATETIME
```

---

## Limitations

- Uses **text-based summarization** — no vector search or semantic retrieval.
- Sessions with fewer than 2 messages do not generate a memory.
- Summaries are not editable; delete directly from the database if needed.
