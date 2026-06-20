---
id: change-requests
title: Change Requests
sidebar_label: Change Requests
---

# Change Requests

Change Requests subject agent configuration, skill, or policy changes to a two-stage approval flow. Once approval is complete, the change is automatically committed to the GitHub repository.

---

## Why Two-Stage Approval?

The capabilities and permissions granted to agents affect the operational risk of the organization. The two-stage approval flow ensures:

- **Department Manager (dept_head)** evaluates technical and operational suitability.
- **Admin (executive+)** makes the final decision from a company policy and security standpoint, and writes the change to Git.

---

## Status Flow

```
submitted
    ↓ dept_head approval
dept_head_approved
    ↓ admin approval + GitHub commit
committed
```

A request can be rejected at any stage:

```
submitted      → rejected  (rejected by dept_head)
dept_head_approved → rejected  (rejected by admin)
```

| Status | Description |
|---|---|
| `submitted` | Request submitted, awaiting department approval |
| `dept_head_approved` | Department approved, awaiting admin approval |
| `admin_approved` | Admin approved, committing to GitHub |
| `committed` | Successfully written to Git; SHA link available |
| `rejected` | Rejected (can occur at either stage) |

---

## Request Types

| Type | Description |
|---|---|
| `agent_config` | Modifying the agent's model, system prompt, or base configuration |
| `skill` | Adding a new skill to an agent or updating an existing skill |
| `policy` | Modifying the guardrail policy applied to an agent |

---

## Creating a Request

Change Requests are created directly from the **Agents** page. When a change is made to an agent configuration, the "Create Change Request" flow is triggered; the request title, type, and proposed configuration are filled in automatically.

---

## Change Requests Page

The **Change Requests** (`/change-requests`) page is accessible to users with `dept_head` role or above.

### Filtering

The filter bar at the top of the page shows the following statuses:

| Filter | Shows |
|---|---|
| All | All requests |
| Pending | Those with `submitted` status |
| Department Approved | Those with `dept_head_approved` status |
| Committed | Those with `committed` status |
| Rejected | Those with `rejected` status |

### Request Detail

Clicking on any request row opens an expanded panel:

- **Approval Flow** — Department and admin approval/rejection timestamps and notes
- **Proposed Changes** — JSON diff of the change
- **GitHub SHA** — If committed, a clickable GitHub commit link

### Action Buttons

**Department Manager** (`dept_head+`) for `submitted` requests:

- **Approve (Department)** — Moves the request to `dept_head_approved` status
- **Reject** — Moves the request to `rejected` status

**Admin** (`executive+`) for `dept_head_approved` requests:

- **Admin Approve & Commit** — Approves the request and automatically commits to GitHub; status becomes `committed`
- **Reject** — Moves the request to `rejected` status

An optional **note** can be added for either action. The note appears in the approval flow history.

---

## Relationship with GitHub Integration

When admin approval is complete, the system:

1. Authenticates the GitHub repository linked to the company using a PAT.
2. Updates the agent configuration file.
3. Commits the change with a message such as `feat: update agent config`.
4. Writes the commit SHA to the request record.

If GitHub integration is not set up, admin approval still works but the commit step is skipped.

To set up GitHub integration → [GitHub Integration](./github-integration.md)

---

## API Endpoints

| Endpoint | Method | Description | Permission |
|---|---|---|---|
| `/change-requests` | POST | Create new request | `agent_owner+` |
| `/change-requests?company_id=` | GET | Request list (filtered) | `dept_head+` |
| `/change-requests/{id}/dept-approve` | POST | Department approval | `dept_head+` |
| `/change-requests/{id}/dept-reject` | POST | Department rejection | `dept_head+` |
| `/change-requests/{id}/admin-approve` | POST | Admin approval + commit | `executive+` |
| `/change-requests/{id}/admin-reject` | POST | Admin rejection | `executive+` |
