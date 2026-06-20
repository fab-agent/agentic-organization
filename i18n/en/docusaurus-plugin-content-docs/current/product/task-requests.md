---
id: task-requests
title: Task Requests
sidebar_label: Task Requests
---

# Task Requests

A Task Request is when a user asks the system to assign an appropriate agent by specifying a department or skill filter. The platform automatically selects the matching agent and sends a notification to the responsible user.

---

## Flow

```
User creates a task request
    ↓
System selects the appropriate agent based on department and/or skill filter
    ↓
The agent's responsible user (responsible_user) receives a notification in their Inbox
    ↓
The responsible user runs or rejects the task
    ↓
The result appears in the Inbox of the user who created the request
```

---

## Creating a Task Request

On the **Inbox** (`/inbox`) page, click the **Task Request** button. In the form that opens:

| Field | Required | Description |
|---|---|---|
| **Department** | No | Narrows the search to a specific department |
| **Skill Filter** | No | Keyword to search in agent skills (e.g. `analysis`, `report`) |
| **Title** | Yes | Task title |
| **Description** | Yes | Task details — the base prompt sent to the agent |

When the **Submit** button is pressed, the system immediately finds the appropriate agent and sends a notification to their responsible user.

:::info Agent Matching Logic
The system lists `active` agents in the specified department whose skills match the filter, then selects the best match. If multiple agents match, the skill match score is used first; if scores are equal, the agent that is currently idle is preferred.
:::

---

## Task Statuses

| Status | Description |
|---|---|
| `pending` | Request created, no agent assigned yet |
| `assigned` | A matching agent was found and the responsible user was notified |
| `running` | Task is being executed via LLM API |
| `completed` | Task completed successfully; result is in the Inbox |
| `rejected` | The responsible user rejected the task |

---

## Responsible User Approval

When a task is assigned, a card appears in the responsible user's Inbox under the **Tasks Awaiting Your Approval** section.

On the card:
- Task title and description
- Optional **note** field (reason for running or rejecting)
- **Run** button — sends the task to the agent; the LLM response appears in the Inbox
- **Reject** button — rejects the task; the requester receives a notification

---

## Relationship with Inbox

The task request system works in direct integration with the Inbox:

| Source | Recipient | Content |
|---|---|---|
| `task_request` | Responsible user | New task assigned notification |
| `task_result` | User who created the request | Task completed + agent output |

For Inbox details → [Inbox](./inbox.md)

---

## API Endpoints

| Endpoint | Method | Description | Permission |
|---|---|---|---|
| `/task-requests` | POST | Create a new task request | `user+` (all roles) |
| `/task-requests?company_id=` | GET | List of requests | `user+` |
| `/task-requests/{id}/run` | POST | Run the task | Responsible user |
| `/task-requests/{id}/reject` | POST | Reject the task | Responsible user |
