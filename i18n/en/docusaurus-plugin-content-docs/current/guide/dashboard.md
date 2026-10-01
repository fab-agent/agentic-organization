---
sidebar_position: 11
---

# Dashboard

The **Dashboard** (`/`) is the summary page that opens when you sign in. Everyone sees it; the content fills in according to your role and the active company.

## Company identity

Company name, sector, website, **vision**, **mission**, **values** and **goals**. You edit this information here (pencil button). Agents draw on this information while working, so keeping it current affects the quality of agent replies.

## Numbers

Total personnel, active agents, departments and policies.

## Telemetry

| Card | Content |
|---|---|
| **Company Telemetry** | Today's session count, active sessions, today's **token** consumption, number of memory (summary) records |
| **My Activity** | Sessions of your agents, token consumption, long-term memory summaries, recent sessions |
| **Agent SLA & Success Rate** | For each agent: session count, tokens, flow success and delegation completion rate |

Token counts rely on usage data from the provider; they are an indicator for cost tracking, not an invoice.

## New version notice

Once an hour the system checks GitHub for the latest release (it caches the result). If there is a new version a notice appears on the Dashboard.

## Quick Access

Shortcuts to Agents, Personnel, Settings and the Org Chart.

## Audit log

Important actions (creating, updating, deleting records, approvals) are listed on the **Settings → Audit Log** tab: who changed which record, when, and with which action. This log is informational. The **tamper-evident** audit chain in the developer workstation layer is separate: [Audit Chain](/workstation/audit-chain).
