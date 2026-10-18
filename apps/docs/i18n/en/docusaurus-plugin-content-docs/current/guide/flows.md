---
sidebar_position: 7
---

# Autonomous Flows

A flow is a scheduled task in which an agent runs **by itself at set times**. The result lands in the **Inbox** of the agent's owner. Examples: a cash report every morning, a weekly supplier summary, an hourly news scan.

**Where:** **Flows** (Agent owner and above).

## Creating a flow

With **New Flow** you enter:

| Field | Description |
|---|---|
| Flow name | Required |
| Agent | The agent that will run; required |
| Schedule | **Cron** format with 5 fields: `minute hour day month day-of-week`; required |
| Description | Optional |
| Task prompt | The instruction given to the agent at each run; required |
| Enable | If off, it is not scheduled |

Cron examples:

| Expression | Meaning |
|---|---|
| `0 9 * * 1-5` | Every weekday at 09:00 |
| `*/15 * * * *` | Every 15 minutes |
| `0 8 * * 1` | Every Monday at 08:00 |

:::caution Time zone: UTC
The scheduler runs in **UTC**. For 09:00 Turkey time (UTC+3), write `0 6 * * *`.
:::

## Managing

The flow list shows the last run time and status (success / error). **Run Now** runs it once without waiting for the schedule. You can edit a flow, make it inactive or delete it. Changes reach the scheduler within a short time.

## Where does the output go?

- **Inbox:** a message to the agent's owner (if none is found, to one of the company's executives). → [Task Requests and Inbox](/guide/tasks-and-inbox)
- **Telegram:** if a bot is defined for the company, the summary is also sent there. → [Settings → Integrations](/guide/settings#integrations)
- The flow record keeps the first part of the last output (500 characters) and the error message.

## Tool use in flows

A flow can use the agent's skills (for example web search); however, currently **tool calling is supported only for models using the Anthropic protocol**. With other models the flow only produces text without using tools. At most 8 tool steps are taken in one turn.

If an image-generating model is selected (for example Qwen Image, DALL-E and compatibles) the flow generates an image.

## Multiple servers

Even if there are several running processes (workers), **only one** process runs the scheduled flows (through a lock file); so a flow is never triggered twice.
