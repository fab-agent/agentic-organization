---
sidebar_position: 4
---

# Agents

An agent is an AI model bound to a personnel record with its skills and policies. Every agent has a **responsible human**; the agent's outputs and approval requests go to that person.

**Where:** **Structure → Agents**.

## Creating an agent

The **New Agent** button asks for the following:

| Section | Field | Description |
|---|---|---|
| Basic information | Agent name, slug, title/role, status | The slug is used as the agent's address when tasks are handed between agents |
| Model and connections | **LLM model** | Models of providers whose key is defined are listed. If a model without a key is selected, a warning appears in chat |
| | **Responsible employee** | The human who oversees the agent |
| | **Department** | When selected, that department's policies are added automatically |
| Job description | Free text | The **Suggest Skills** button analyses the job description and suggests suitable skills |
| Skills | Pick from library / add tool | See [Skills and Policies](/guide/skills-and-policies) |
| Policies | Department policies + extra policies | |

On creation, the agent becomes a personnel record (**type: agent**) and an agent configuration; it appears on the organization chart like other employees.

## Statuses

| Status | Meaning |
|---|---|
| **Draft** (`draft`) | Being prepared, not yet open for use |
| **Active** (`active`) | Ready for use; selectable in chat, included in flow and task routing |
| **Archived** (`inactive`) | Hidden from the list; record and history are kept |

**Archive** keeps the record; **Delete** is permanent. If you want to keep the history, archive.

## Sending a change for approval

Instead of changing an agent's configuration directly, you can open a request with the **Change Request** button on the row (type: agent configuration, skill or policy). The request goes through two-stage approval, is applied when approved and, if wished, is written to Git. → [Change Requests](/guide/change-requests)

## The agent's memory

When a chat is closed, the system summarizes that session and adds it to the agent's **long-term memory**; these summaries are used as context in later sessions. Details: [Chatting with an Agent → Memory](/guide/chat#memory).
