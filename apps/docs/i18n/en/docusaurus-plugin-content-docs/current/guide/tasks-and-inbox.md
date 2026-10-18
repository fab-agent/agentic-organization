---
sidebar_position: 8
---

# Task Requests and Inbox

## Inbox

The Inbox is where everything that reaches you is collected: **flow results**, **task requests** and system notifications. Its address is `/inbox` (it has no link in the sidebar; people with the **User** role are taken straight to it at sign-in).

- Unread messages are counted with a badge; the list refreshes itself every 30 seconds.
- Filters: **All**, **This week**, **This month**, **Only new**.
- Opening a message marks it read; there are **Mark all read** and delete buttons. Each user sees and deletes only their own messages.

## Task request: routing work to the right agent

If you do not know which agent a piece of work should go to, create a **Task Request**; the system finds a suitable agent.

1. In the Inbox, press **Task Request**.
2. Write a **Title** and a **Description** (both required). If you like, give a **department** and a **skill filter** (for example `analysis`, `report`).
3. The system routes it like this:
   1. It filters the company's **active** agents by the skill filter.
   2. It prefers an agent in the requested department, otherwise in parent departments (if no department was given, it searches the whole company).
   3. It assigns the first suitable agent and sends a notification to the agent's **responsible human**.

If no suitable agent is found the request stays **pending** (`pending`); if one is found it becomes **assigned** (`assigned`).

## The responsible person's approval

The owner of the assigned agent sees the request in the **Tasks Awaiting Your Approval** section of the Inbox:

- **Run:** The agent runs the task; the result streams live and the request becomes **completed** (`completed`). If an error occurs, the request goes back to a retryable state.
- **Reject:** An optional note is written; the request becomes **rejected**. You can see the note in the request's record.

Only the responsible person can run or reject; without human approval no agent takes on a task. You can also approve pending tasks with the **Telegram bot** (`/onaylar`).

| Status | Meaning |
|---|---|
| `pending` | No suitable agent was found |
| `assigned` | Agent assigned, awaiting the owner's approval |
| `running` | Running |
| `completed` | Done, result recorded |
| `rejected` | The owner rejected it |
