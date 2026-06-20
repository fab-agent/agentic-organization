---
sidebar_position: 3
---

# A2A Delegation — Agent-to-Agent Task Transfer

The **Delegation** (`/a2a`) page tracks and manages A2A (Agent-to-Agent) flows where one agent delegates a task to another. Every task transfer passes through two human approval checkpoints.

---

## Why Two Approvals?

Cross-department task transfers involve two independent decisions:

1. **Task approval** — "Should we hand this task off to the other party?"
2. **Result approval** — "Should we use the output produced by the other party?"

Separating these two controls allows sensitive departments — such as Legal or Finance — to oversee where their own outputs are forwarded.

---

## State Machine

```
pending_approval
      │
      ├── [Rejected]  → rejected  ✗
      │
      └── [Approved]  → approved
                │
                └── [Agent started working] → running
                          │
                          └── [Completed] → pending_result_approval
                                    │
                                    ├── [Rejected] → rejected  ✗
                                    │
                                    └── [Approved]  → completed  ✓
```

| Status | Description |
|---|---|
| `pending_approval` | The target agent's responsible person is waiting to approve the task |
| `approved` | Task approved; agent is ready to start |
| `running` | Target agent is actively executing the task |
| `pending_result_approval` | Result is ready; the source agent's responsible person will review it |
| `completed` | Both approvals received; result has been delivered |
| `rejected` | Rejected at any stage |

---

## Using the Delegation Page

### Tabs

- **Pending** — Requests in `pending_approval` or `pending_result_approval` status
- **All** — All requests including full history

### Request Card

Each request displays:

- Source agent → Target agent arrow
- Task description (truncated; expands on click)
- Status badge (color-coded)
- Action button (changes based on approval stage)
- Creation date

### Pending Counter

An amber badge appears next to the **Delegation** menu item in the sidebar. When the number of pending requests is > 0, an amber pulse dot also appears on the company card.

---

## Approval Steps

### Task Approval (pending_approval)

When the request is in `pending_approval` status and the **"Approve"** button is clicked:

```
POST /a2a/requests/{id}/approve
{ "approver_id": "personnel_uuid" }
```

The status is updated in sequence: `approved → running → pending_result_approval` (the agent runs in the background).

### Result Approval (pending_result_approval)

The agent has completed the task and the result is recorded. When the **"Approve Result"** button is clicked:

```
POST /a2a/requests/{id}/approve-result
{ "approver_id": "personnel_uuid" }
```

The status becomes `completed`.

### Rejection

A **"Reject"** button is available at both stages:

```
POST /a2a/requests/{id}/reject
{ "approver_id": "personnel_uuid" }
```

The status becomes `rejected` (a terminal state).

---

## Approver Selection

At the top of the Delegation page there is a dropdown listing the company's human personnel. The selected person is used as the `approver_id` for approval and rejection actions.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/a2a/requests` | Create a new delegation request |
| `GET` | `/a2a/requests` | List requests (filterable by `company_id`) |
| `POST` | `/a2a/requests/{id}/approve` | Task approval |
| `POST` | `/a2a/requests/{id}/approve-result` | Result approval |
| `POST` | `/a2a/requests/{id}/reject` | Reject |
| `GET` | `/a2a/requests/pending-count` | Number of pending requests (filtered by `company_id`) |

The `company_id` query parameter is supported on all list and count endpoints.

---

## Data Model Summary

```
A2ARequest
  ├── id                  UUID
  ├── from_session_id     Requesting session
  ├── from_agent_id       Requesting agent
  ├── to_agent_id         Target agent
  ├── task                Task description (free text)
  ├── status              Status (see above)
  ├── result              Target agent's response (nullable)
  ├── approver_id         Personnel who made the last approval/rejection
  ├── created_at
  └── updated_at
```

---

## Example Scenario

```
1. Sales agent (Ali) requests a Q2 churn analysis during a conversation.
   An A2ARequest is created:
     from_agent_id: ali_agent
     to_agent_id:   bulent_agent (Analytics Dept.)
     task: "Q2 2026 churn analysis — segment-based attrition rates"
     status: pending_approval

2. Bülent's responsible person sees the request on the Delegation page,
   reviews the task content, and clicks "Approve".
   status: approved → running

3. Bülent's agent executes the task and saves the result.
   status: pending_result_approval

4. Ali's responsible person reads the result, finds it acceptable, and approves.
   status: completed

5. The result is injected into Ali's conversation context.
```

---

## Related Documents

- [A2A Architecture Design](../product/a2a-architecture.md)
- [Agent Runtime](./agent-runtime.md)
- [Jobs Page](./chat-ui.md)
