---
id: user-roles
title: User Roles
sidebar_label: User Roles
---

# User Roles

fab.engineering defines five distinct platform roles. Which pages are visible and which actions are available depend on the assigned role.

---

## What Can I See Based on My Role?

### Founder (`founder`)

The fully authorized owner of the platform. Has access to all pages and actions.

**Accessible pages:** Structure · Departments · People · Organization · Agents · Change Requests · Autonomous Flows · Inbox · Jobs · Delegation · Settings

**Can do:**
- Full company, department, personnel, and agent management
- Invite users to the platform and assign roles
- Reset other users' passwords
- Manage AI provider keys and Git integration on the Settings page

---

### Executive (`executive`)

Has nearly the same permissions as Founder. Cannot add users at or above their own level.

**Accessible pages:** Structure · Departments · People · Organization · Agents · Change Requests · Autonomous Flows · Inbox · Jobs · Delegation · Settings

**Can do:**
- Full organization and personnel management
- Invite users with the `dept_head`, `agent_owner`, and `user` roles
- Reset passwords
- Full access to the Settings page

---

### Department Manager (`dept_head`)

An operational management role. Can view the organization structure and personnel; cannot access the Settings page.

**Accessible pages:** Structure · Departments · People · Organization · Agents · Change Requests · Inbox · Jobs · Delegation

**Can do:**
- Create and edit departments, and establish hierarchy
- Add personnel and send platform invitations by email
- Configure agents and manage their status
- Approve or reject change requests on behalf of the department
- View the org map (personnel and department views)
- Chat with agents (Jobs)
- Read Inbox messages and manage task requests
- Delegation actions

---

### Agent Owner (`agent_owner`)

An agent-focused operational role. Cannot view the organization structure.

**Accessible pages:** Agents · Autonomous Flows · Inbox · Jobs · Delegation

**Can do:**
- View and configure the agents they are responsible for
- Create and manage autonomous flows
- Read Inbox messages and process pending task requests
- Chat with agents
- Delegation actions

---

### User (`user`)

The most limited role. Can only access the daily workspace.

**Accessible pages:** Inbox · Jobs · Delegation

**Can do:**
- Create task requests (request an agent by filtering by department/skill)
- Read Inbox messages and process pending task requests
- Chat with agents (Jobs page)
- Delegation actions

---

## Comparison Table

| Page / Action | User | Agent Owner | Department Manager | Executive | Founder |
|---|:---:|:---:|:---:|:---:|:---:|
| Inbox | Yes | Yes | Yes | Yes | Yes |
| Jobs (Chat) | Yes | Yes | Yes | Yes | Yes |
| Delegation | Yes | Yes | Yes | Yes | Yes |
| Create Task Request | Yes | Yes | Yes | Yes | Yes |
| Agents | — | Yes | Yes | Yes | Yes |
| Autonomous Flows | — | Yes | Yes | Yes | Yes |
| Structure (Dashboard) | — | — | Yes | Yes | Yes |
| Departments | — | — | Yes | Yes | Yes |
| People | — | — | Yes | Yes | Yes |
| Organization (Org Map) | — | — | Yes | Yes | Yes |
| Change Requests | — | — | Yes | Yes | Yes |
| Department Approval (Change) | — | — | Yes | Yes | Yes |
| Admin Approval + Git Commit | — | — | — | Yes | Yes |
| Settings (AI + Git) | — | — | — | Yes | Yes |
| Invite Users | — | — | Yes | Yes | Yes |
| Reset Password | — | — | Yes | Yes | Yes |

---

## How Do You Find Out Your Role?

Click the avatar menu in the top-right corner → open the **Profile** page.

On the Profile page, the **Company Memberships** section shows each company you belong to and your role within that company, displayed as a colored badge.

---

## Changing Your Role

Role changes cannot be made through self-service. A manager with `dept_head` or higher permissions must re-invite you or edit your existing membership. Contact your company administrator to request a role change.

---

## Technical Details

For the authentication flow, token structure, and backend API → [Authentication and Roles](../platform/auth-and-roles.md)
