---
sidebar_position: 9
---

# Delegation Between Agents (A2A)

An agent can hand work it cannot do itself to **another agent**. Every handover passes through two approvals by the people concerned. So an agent cannot run another agent without a human seeing it.

## Flow

```
Agent A calls the delegate_to_agent tool
        ↓
  pending_approval   → The target agent's owner approves the task
        ↓
     running         → The target agent runs the task
        ↓
  pending_result_approval → The owner approves the result
        ↓
    completed        → The result returns to Agent A's session as a report
```

It can be **rejected** (`rejected`) at any stage; the reason for rejection is recorded.

If work is handed to several agents in parallel (for example an orchestrator agent distributing work to specialists), when all results are complete they are compiled into a single **executive report** and written to the session that started it.

## Setup

1. Add the **Agent delegation** (`delegate_to_agent`) skill to the agent that will hand off work ([Skills](/guide/skills-and-policies)). If you like, you can fix the target agent in the skill's setting.
2. In the agent's instruction (job description or policy), write which work goes to which agent. The target agent is addressed by its **slug** (visible in **Structure → Agents**).

## The Delegation page

The **Delegation** (`/a2a`) page lists the handovers in the company. The badge in the sidebar shows the number of handovers awaiting approval.

| Tab | Content |
|---|---|
| **Pending** | Those awaiting approval |
| **All** | Everything, including history |

Each card shows the task, context, the result (if any) and the approver. The buttons change with the status:

- **Approve & Run Task** → the task starts.
- **Approve Result** → the result returns to the requesting session. When the target agent finishes, the result **waits for approval** and does not reach the chat until approved.
- **Reject** / **Reject Result**.

The person who can approve is the target agent's **responsible human**; if someone else tries to approve, the system refuses. You can also see and approve pending handovers through the **Telegram bot** (the `/onaylar` command; see [Settings → Integrations](/guide/settings#integrations)).

:::note
Delegation requests currently do not drop a message into the Inbox. Follow pending work from the Delegation page, from the badge or from Telegram.
:::
