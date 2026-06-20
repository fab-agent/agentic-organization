---
sidebar_position: 2
---

# Jobs Page — Chatting with an Agent

The **Jobs** (`/chat`) page lets you have real-time conversations with agents on the platform. The left panel shows sessions, the center area shows messages, and the right panel shows information about the active agent.

---

## Page Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Sessions           │  Chat Area                 │  Agent Info   │
│  ─────────────────  │  ──────────────────────    │  ──────────── │
│  [+ New Session]    │                            │  Model        │
│                     │  [Assistant message]       │  Skills       │
│  Session 1          │  [User message]            │  Department   │
│  Session 2          │  [Tool call]               │               │
│  Session 3          │  [Tool result]             │               │
│                     │  ──────────────────────    │               │
│                     │  [Message input field]     │               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Starting a New Session

1. Press the **"New Session"** button in the left panel or click the `+` icon.
2. The agent picker opens — all active agents in your company are listed.
3. Select an agent.
4. Type your first message and send it.

:::tip URL parameter
To start a conversation with a specific agent directly, append `?agent=<agent_id>` to the URL: `/chat?agent=abc123`
:::

---

## Sending Messages

- Type your message in the text box.
- **Enter** → send. **Shift+Enter** → new line.
- While a message is being sent, the input field and send button are disabled.
- A running response can be cancelled by pressing the **Stop** button.

---

## Real-Time Streaming

While the agent is responding, the message appears letter by letter (streaming). When the agent decides to use a tool:

1. A tool call box appears (tool name + arguments)
2. The tool runs and a result box is added
3. The agent analyzes the result and completes its text response

Example tool call (as it appears in the interface):

```
🔧 web_search
   query: "Q2 2026 e-commerce growth rate"

✅ web_search
   Turkey's e-commerce market grew 22% in Q2 2026...
```

---

## Agent Info Panel

The right panel displays the following information about the active agent:

| Field | Description |
|---|---|
| **Model** | The AI model in use (e.g. `gemini-2.0-flash`) |
| **Skills** | List of active skills, each labeled with a `builtin` / `mcp` / `http` / `function` badge |
| **Department** | The department the agent belongs to |

The panel can be closed; click the info icon in the top right to reopen it.

---

## Session History

All unclosed (`active`) sessions are listed in the left panel. Clicking a session loads its full message history. A session is closed via `DELETE /sessions/{id}`.

---

## Company Change

When the active company is changed:
- All session and message data is cleared
- The agent list is reloaded for the new company
- The active session is reset

This behavior is implemented using `$effect`:

```svelte
$effect(() => {
  if (companyStore.active) {
    activeSession = null;
    messages = [];
    selectedAgent = null;
    loadAgents();
    loadSessions();
  }
});
```

---

## Frontend API — streamMessage

The `streamMessage()` function in `src/lib/api/sessions.ts` consumes SSE via `fetch` + `ReadableStream` and returns an async generator:

```typescript
for await (const event of streamMessage(sessionId, userInput, abortSignal)) {
  switch (event.type) {
    case 'text':        // accumulate streaming text
    case 'tool_call':   // show tool call box
    case 'tool_result': // show tool result
    case 'done':        // finalize message, get message_id from DB
    case 'error':       // show error
    case 'stream_end':  // close stream
  }
}
```

An ongoing stream can be cancelled via `AbortController`.

---

## Related Docs

- [Agent Runtime](./agent-runtime.md)
- [Message Content Component](./message-rendering.md)
- [A2A Delegation](./a2a-delegation.md)
