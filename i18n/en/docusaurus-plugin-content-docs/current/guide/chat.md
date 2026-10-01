---
sidebar_position: 6
---

# Chatting with an Agent (Jobs)

The **Jobs** page is where you talk with agents. The left panel has the agent list and past sessions, the middle holds the chat, and on request the right shows agent information.

## Starting a chat

1. Pick an agent from the left panel. The company's agents are listed; you see a warning on an agent whose model has no defined key. Instead of chatting with a draft or archived agent, it is recommended to make the agent **active** first.
2. Press **New Chat** and type your message. `Enter` sends, `Shift+Enter` opens a new line.
3. The reply streams as it is written. You can interrupt it with **Stop**.

The agent calls its defined skills (web search, database query and so on) itself when needed; the calls are visible inside the chat.

## Attaching files

With the paperclip button you can attach a **PDF, text (TXT), CSV or image**. The file content is given to the agent as context.

## How replies look

Replies are rendered as Markdown: headings, tables, lists, colored code blocks. In addition:

- **JSON** is formatted automatically.
- For **HTML** blocks there is a collapsible preview next to the source.
- **Mermaid** code blocks turn into diagrams.

## Jobs running in the background

If the agent starts a long job (for example a task handed to another agent), an "Agent is working in the background" notice appears; when the result is ready it lands in the chat.

## Sessions

Each chat is a **session**. Past sessions are listed in the left panel and can be opened and continued. If you switch the active company, the list refreshes for that company's agents.

## Memory

When a session is closed (if it has at least two messages), the system automatically creates a **summary** and saves it to the agent's long-term memory. In later sessions these summaries are given to the agent as context; the agent "remembers" earlier conversations. You can see memory summaries on the **Dashboard** and in the personnel record.

On PostgreSQL installations, past sessions and summaries are also indexed for **semantic search** (pgvector); the agent can find relevant past information this way too.

## Agent information panel

The info button at the top right shows the agent's department, manager and tools/skills (inactive ones are marked).
