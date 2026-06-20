---
sidebar_position: 5
---

# A2A (Agent-to-Agent) Collaboration Architecture

This document describes the design of the A2A protocol in 3PA, which allows agents across different departments to request tasks from one another.

---

## Why A2A?

In an organization, agents can leverage each other's capabilities rather than operating in isolation. For example:

- A Sales agent can request customer analysis from an Analytics department agent.
- An HR agent can request a contract draft from a Legal agent during a hiring process.
- A Finance agent can use a Data agent's calculation tools to generate a report.

These requests involve two departments and two responsible humans. The A2A protocol manages this cross-department interaction in an **auditable, approval-based** manner.

:::note Two-stage approval requirement
A single approval is not sufficient because both the assignment of the task (which agent will work on it and what it will do) and the use of the result (what the agent returned and whether the requesting party can use that information) require separate managerial decisions. The two-stage approval makes both of these decisions explicit.
:::

---

## Flow Diagram

```
Requesting Agent (A)
        │
        │  "I want you to handle this task"
        ▼
  Create A2ARequest
  status: pending_approval
        │
        │  (Notification: Agent B's responsible person)
        ▼
  Responsible Human (Department B)
        │
    ┌───┴───────────────┐
    │ Reject            │ Approve
    ▼                   ▼
  status:          status: approved
  rejected              │
                        │
                        ▼
                  Agent B runs
                  status: running
                        │
                        ▼
                  Task completed
                  status: pending_result_approval
                        │
                  (Notification: Agent A's responsible person)
                        │
                    ┌───┴───────────────┐
                    │ Reject            │ Approve
                    ▼                   ▼
              status:            status: completed
              rejected           Result returned to Agent A
```

---

## Two-Stage Approval

| Stage | Trigger | Approver | Description |
|---|---|---|---|
| **Task approval** | When A2ARequest is created | Agent B's `responsible_id` person | "Should this task be assigned to B?" |
| **Result approval** | When Agent B completes the task | Agent A's `responsible_id` person | "Should this result be passed to A?" |

These two checkpoints keep cross-department data flow fully under control. Particularly sensitive departments (Legal, Finance) can filter the output of their own agents from being forwarded to other departments at the second approval stage.

---

## Data Model

```
A2ARequest
  ├── id                     UUID, primary key
  ├── from_session_id        FK → AgentSession (requesting session)
  ├── from_agent_id          FK → AgentConfig (requesting agent)
  ├── to_agent_id            FK → AgentConfig (target agent)
  ├── task                   string — task description (free text)
  ├── status                 string — status (see below)
  ├── result                 string (nullable) — Agent B's response
  ├── approver_id            FK → Personnel (human who approved/rejected)
  ├── created_at             datetime
  └── updated_at             datetime
```

### Status Lifecycle

```
pending_approval
      │
      ├── [Rejected] → rejected  (final state)
      │
      └── [Approved] → approved
                │
                └── [Agent B started running] → running
                          │
                          └── [Completed] → pending_result_approval
                                    │
                                    ├── [Rejected] → rejected  (final state)
                                    │
                                    └── [Approved] → completed  (final state)
```

| Status | Meaning |
|---|---|
| `pending_approval` | Task awaiting approval (Agent B's responsible person) |
| `approved` | Task approved, Agent B will begin running |
| `running` | Agent B is actively executing the task |
| `pending_result_approval` | Result is ready, awaiting approval from Agent A's responsible person |
| `completed` | All approvals received, result forwarded to Agent A |
| `rejected` | Task or result was rejected at any approval stage |

---

## Notification Flow

In practice, notifications can be delivered through the following channels (future phases):

- **In-platform** — Pending approval list on the responsible personnel's dashboard
- **Email** — Notification to the assigned email address (configured via AppConfig)
- **Webhook** — POST to external systems (Slack, Teams, etc.)

---

## Example Scenario

```
Scenario: Sales Agent (Ali) → Analytics Agent (Bülent)

1. Ali's agent determines during a conversation:
   "Let me request a Q2 customer churn analysis from the Analytics department."

2. An A2ARequest is created:
   from_agent_id: ali_agent_id
   to_agent_id:   bulent_agent_id
   task:          "Q2 2026 churn analysis — segment-based churn rates"
   status:        "pending_approval"

3. Bülent's responsible person (Çiğdem) receives a notification.
   Çiğdem finds the task appropriate and approves it.
   status → "approved" → "running"

4. Bülent's agent executes the task and saves the result.
   status → "pending_result_approval"

5. Ali's responsible person (Mehmet) reviews the result.
   The result is appropriate; he approves it.
   status → "completed"

6. Ali's agent receives the result and continues the conversation.
```

---

## Design Notes

:::tip Trust between agents
Agents cannot call each other directly; every call passes through a human approval checkpoint. This prevents an autonomous A2A chain from growing in an uncontrolled manner.
:::

:::note `from_session_id` relationship
The request is tied to a specific conversation session. This allows the A2A result to be injected into the correct conversation context and the conversation history to be tracked.
:::

---

## Related Documents

- [Agent Runtime Architecture](../architecture/runtime.md)
- [Agent Management](./agent-management.md)
- [Personnel Portal](./personnel-portal.md)
