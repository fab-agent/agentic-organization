---
sidebar_position: 5
---

# Skills and Policies

## Skills

A skill is a tool the agent can use. The **Structure → Skills** page is a company-wide **library**: a skill is defined once and assigned to any agents.

Each skill has a name, a slug, a short description, a **type**, Markdown **content** (an instruction telling the agent how and when to use it), a type-specific setting and an active/inactive status.

### Skill types

| Type | What it does | Setting |
|---|---|---|
| **Built-in** (`builtin`) | The platform's ready-made tools | The list below |
| **MCP** | Calls a tool of an MCP server (JSON-RPC over HTTP; the server must offer the `…/call` address) | Server address; authentication: none, API key or Bearer token |
| **HTTP API** | Calls a REST webhook or API (`POST` by default, `GET` selectable) | Address, method, fixed headers |
| **Function** | Custom Python code; needs the signature `run(args: dict) -> str`. Runs in a restricted environment (few built-in functions) with a **5-second** timeout | Code |
| **Database** | Runs an SQL query on a connected database | Connection and schema ([Settings → Databases](/guide/settings#databases)) |

For technical schemas: [Skill Types](/technical/skill-types).

### Built-in tools

| Tool | Function |
|---|---|
| Web search (`web_search`) | Web search with DuckDuckGo |
| Chart generation (`text_to_chart`) | A chart from JSON/CSV data. **Currently a placeholder:** the tool is called but does not produce a real chart |
| Write journal (`journal_write`) | Appends a Markdown entry to the session journal |
| Agent delegation (`delegate_to_agent`) | Hands the task to another agent → [Delegation](/guide/delegation) |
| Instagram post (`instagram_post`) | Posts to an Instagram Business account → [Settings → Social media](/guide/settings#integrations) |
| WhatsApp message (`whatsapp_send`) | Sends a message through the WhatsApp Business API |

### Assigning to an agent

When creating or editing an agent, choose from the library in the **Skills** section or add a tool specific to that agent. Skill edits go to the **approval process** (department head + executive); until approved, the old version is in force. → [Change Requests](/guide/change-requests)

## Policies

A policy is a written rule agents must follow; it is written as a **Markdown document**. It has three scopes:

| Scope | Applies to |
|---|---|
| **Company** | All agents in the company |
| **Department** | Agents in that department (automatically when linked to the department) |
| **Agent** | Only that agent (an extra policy specific to the agent) |

Policies are created, edited and made active/inactive from the **Structure → Policies** page. Edits go to approval like skills.

### How does a policy affect the agent?

- The **names** of the policies the agent must follow are added to its instruction.
- If the policy text contains a code block marked `policy`, `yaml` or `json`, the **policy engine** reads it as an executable rule and evaluates the agent's tool calls as `allow / ask / deny`. By default the engine works in **trial mode** (`dry_run`: the decision is recorded but not enforced). The mode (`off`, `dry_run`, `enforce`) can currently only be changed through the API: `PUT /policies/config`. Details: [Policy Engine](/workstation/policy-engine).

So a plain-text policy is a guide steering the agent; for **hard enforcement** you need to write a rule block and put the engine in `enforce` mode (there is no setting for this in the interface yet).
