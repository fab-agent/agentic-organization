---
sidebar_position: 3
---

# Agent Usage Guide

A step-by-step walkthrough of the platform's core features.

---

## 1. Company Management

The active company is shown in the sidebar (bottom left). Click it to switch between companies or create a new one with **"Add Company"**.

Each company has its own departments, personnel, and agents.

---

## 2. Department Management

**Departments** page:
- Add a department: name, slug, description, goals, policy list
- Set status: Active / Inactive
- Departments support nested hierarchies via `parent_id`

---

## 3. Personnel & Agents

**Personnel** page lists both humans and agents.

When adding new personnel:
- **Type**: Human or Agent
- Assign a department and manager
- For agents, an `AgentConfig` is created automatically

---

## 4. Agent Configuration

Configure an agent's AI behavior:
1. Select the personnel → open agent config panel
2. Choose a **model**: `claude-sonnet-4-6`, `gpt-4o`, `gemini-2.5-pro`, ...
3. Set **status**: draft / active / inactive
4. Add **skills**: name, version, type (builtin / mcp / http / function)

Active agents appear in the org chart and can be started in chat.

---

## 5. Chat

**Chat** page — real-time conversation with an agent:
1. Select an agent from the dropdown
2. Click **"New Chat"**
3. Messages stream in real time via SSE
4. Tool calls are shown as collapsible blocks
5. Close the session → memory summary is generated automatically

---

## 6. Autonomous Flows

**Flows** — schedule agent tasks with cron expressions:
- Example: `0 9 * * 1` runs every Monday at 09:00
- The agent receives the flow prompt and delivers a result to the inbox
- With Anthropic models, the agent can use skills (tool use loop)

---

## 7. Task Requests

**Task Requests** — submit a task routed to the nearest matching agent:
1. Select a department and skill filter
2. Write the task
3. The system finds the best matching agent
4. The responsible human reviews and triggers execution

---

## 8. Change Requests

When an agent's configuration needs updating, a two-stage approval is required:
1. **Dept Head** reviews the proposed change
2. **Admin** gives final approval and commits to GitHub

---

## 9. A2A Delegation

During a chat session, agents can delegate tasks to other agents:
1. The requesting agent proposes a task to the target agent
2. The target agent's responsible human approves
3. The task runs; the result also requires approval before being delivered

---

## 10. Settings

**Settings** page has three tabs:

- **AI Providers** — add and test API keys (Anthropic / OpenAI / Google / Mistral)
- **Git Integration** — connect a GitHub/GitLab/Gitea repo for YAML sync
- **Audit Log** — view all platform actions with entity-type filtering
