---
id: auth-and-roles
title: Authentication and Roles
sidebar_label: Authentication and Roles
---

# Authentication and Roles

fab.engineering uses an invite-based authentication system. Users cannot self-register. All accounts are created by authorized admins and sent to the platform via email invitation.

---

## Login Flow

### Standard Login

1. The user navigates to the `/login` page.
2. They enter their email address and password.
3. They click the **"Log In"** button.
4. On successful login, they are redirected to the home page; the left sidebar adapts to the user's role.

### First Login (with Temporary Password)

Users who have received a new invitation or had their password reset log in with a temporary password:

1. The user goes to the `/login` page and enters their email and temporary password.
2. The system detects that the password is flagged as `force_change`.
3. The user is automatically redirected to the `/set-password` page.
4. The user enters their new permanent password twice.
5. The password is saved and the user is redirected to the home page.

:::caution
The temporary password is valid for **30 minutes**. When it expires, the next time the user attempts to log in, the system automatically generates a new temporary password and sends it to them by email.
:::

---

## Invitation Flow

To add a new user to the platform, follow these steps:

1. Open the relevant human personnel record on the **People** page. Make sure the email field is filled in.
2. Click the **envelope icon** on the personnel row.
3. In the **"Invite"** dialog that opens, select the Platform Role.
4. Click the **"Send Invite"** button.

What happens in the background:
- A 10-character temporary password in `XXXXX-XXXXX` format is generated (uppercase letters + digits).
- The password is hashed with `bcrypt` and saved to the database; `force_change = true` is flagged.
- An invitation email is sent to the personnel's email address via Resend; the email contains the temporary password in plain text.
- The user account and company membership are created.

---

## Password Management

### User Password Change

Logged-in users can update their password from the **"Change Password"** tab on the **Profile** page.

- The current password is not requested (identity is already verified since the session is active).
- The new password is entered twice and saved.

### Admin Password Reset

If a user forgets their password, there is no self-service reset option. The admin follows these steps:

1. Go to the relevant personnel row on the People page.
2. Click the **Reset Password** button.
3. The system generates a new 30-minute temporary password and sends it to the user by email.
4. On their next login, the user is redirected to the `/set-password` page.

---

## Role Hierarchy

The platform has five role levels. Each role encompasses all permissions of the roles below it.

| Role | Name | Description |
|---|---|---|
| `founder` | Founder | Full access — all pages, settings, user management |
| `executive` | Executive | Full access including settings; cannot add new users at the same level |
| `dept_head` | Department Head | Structure, Departments, Personnel, Agents, Org Chart, Jobs, Delegation |
| `agent_owner` | Agent Owner | Agents, Jobs, Delegation |
| `user` | User | Jobs and Delegation only |

---

## Navigation Visibility

Menu items in the left sidebar are filtered based on the user's role:

| Menu Item | Minimum Role |
|---|---|
| Structure (`/`) | `dept_head` |
| Departments (`/departments`) | `dept_head` |
| Personnel (`/personnel`) | `dept_head` |
| Organization (`/org-chart`) | `dept_head` |
| Agents (`/agents`) | `agent_owner` |
| Change Requests (`/change-requests`) | `dept_head` |
| Autonomous Flows (`/flows`) | `agent_owner` |
| Task Requests / Inbox (`/inbox`) | `user` (all roles) |
| Jobs (`/chat`) | `user` (all roles) |
| Delegation (`/a2a`) | `user` (all roles) |
| Settings (`/settings`) | `executive` |

:::info
An employee with the `user` role will only see the **Inbox**, **Jobs**, and **Delegation** pages when they log in to the platform.
:::

---

## Profile Page

Every user can access the **Profile** page from the avatar menu in the top-right corner. The Profile page shows:

- **Name and Email:** Real user information pulled from `authStore`
- **Company Memberships:** A list of the companies the user belongs to and their role in each company (color-coded badge)
- **Change Password tab:** Set a new password without being asked for the current password

---

## Backend API Reference

| Endpoint | Method | Description | Authorization |
|---|---|---|---|
| `/auth/token` | POST | Login — `email` + `password` returns `access_token` | Public |
| `/auth/me` | GET | Logged-in user info + company memberships | Bearer token |
| `/auth/invite` | POST | Create new user + send invitation email | `manager+` |
| `/auth/change-password` | POST | Update password | Bearer token |
| `/auth/reset/{user_id}` | POST | Admin password reset | `manager+` |
| `/personnel/{id}/invite` | POST | Direct invite from a personnel record | `manager+` |

### Token Usage

The `access_token` returned after a successful login is sent as an HTTP header on all authorized endpoint calls:

```
Authorization: Bearer <access_token>
```

The token is signed with the `JWT_SECRET` environment variable. When it expires, the user must log in again.

---

## Notification Infrastructure

Invitation and password reset notifications are delivered via the **Telegram Bot API**. No email infrastructure is required — delivers instantly to an admin chat.

Types of notifications sent:
- **Invitation notification:** The new user's temporary password is sent to the admin chat
- **Password renewal:** A new temporary password is sent when the previous one expires
- **Admin reset:** New temporary password sent after an admin password reset

Configuration: Go to **Settings → Integrations → Telegram Notifications**, enter your BotFather token and admin chat ID.

If Telegram is not configured, temporary passwords are shown in the API response and the UI.
