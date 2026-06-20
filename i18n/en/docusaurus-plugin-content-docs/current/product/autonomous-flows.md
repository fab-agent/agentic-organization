---
id: autonomous-flows
title: Autonomous Flows
sidebar_label: Autonomous Flows
---

# Autonomous Flows

Autonomous Flows are configurations that automatically assign a task to an agent on a cron schedule. At the specified time, the agent executes the task via the LLM API and the result lands in the **Inbox**.

---

## Use Cases

- Daily reports that summarize sales figures every morning
- An agent that scans the customer support queue every weekday morning
- System health checks that run every hour
- An agent that produces a weekly priority suggestion for the team every Monday

---

## Creating a Flow

Go to the **Autonomous Flows** (`/flows`) page and click the **New Flow** button.

### Form Fields

| Field | Required | Description |
|---|---|---|
| **Flow Name** | Yes | A short title that identifies the flow |
| **Agent** | Yes | The agent that will execute the task (only personnel of type `agent` are listed) |
| **Schedule** | Yes | Cron expression — the scheduling rule |
| **Task Prompt** | Yes | The task description sent to the agent |
| **Description** | No | Free text describing the purpose of the flow |
| **Active** | — | Enables or disables the flow |

### Schedule — Cron Format

```
minute  hour  day-of-month  month  day-of-week
  0      9         *          *        1-5
```

The example above runs **every weekday at 09:00**.

Preset templates:

| Template | Cron |
|---|---|
| Every day at 09:00 | `0 9 * * *` |
| Weekdays at 09:00 | `0 9 * * 1-5` |
| Every Monday at 08:00 | `0 8 * * 1` |
| Every hour | `0 * * * *` |

To write a custom cron expression, select the **Custom** option and edit the field directly.

---

## Flow Management

### Enable / Disable

Click the **Active / Inactive** toggle on the list to instantly enable or disable a flow. Inactive flows do not run on schedule, but their record is preserved.

### Run Now

Click the **Play** icon on any row to trigger the flow immediately, independent of its schedule. This is useful for testing. Once the run completes, the result lands in the Inbox.

### Edit / Delete

- The **Edit** button (pencil icon) reopens the flow form; all fields are editable.
- The **Delete** button shows a confirmation dialog and then permanently deletes the flow.

---

## Run Log

The **Last Run** information for each flow is shown in the table. If a run failed, an `Error` badge is displayed. Error details can be found in the corresponding message in the Inbox.

| Column | Description |
|---|---|
| Flow | Name and description |
| Agent | The agent that executed the task |
| Schedule | Cron expression |
| Last Run | Time of the last successful or failed run |
| Status | Active / Inactive |

---

## Relationship with Inbox

Every successful or failed run creates a message tagged **Flow** in the Inbox. The message includes:

- The flow name and which agent executed it
- The response produced by the LLM (task output)
- The run timestamp

For Inbox details → [Inbox](./inbox.md)

---

## API Endpoints

| Endpoint | Method | Description | Permission |
|---|---|---|---|
| `/flows?company_id=` | GET | List flows | `agent_owner+` |
| `/flows` | POST | Create a new flow | `agent_owner+` |
| `/flows/{id}` | PUT | Update a flow | `agent_owner+` |
| `/flows/{id}` | DELETE | Delete a flow | `agent_owner+` |
| `/flows/{id}/run` | POST | Run immediately | `agent_owner+` |
