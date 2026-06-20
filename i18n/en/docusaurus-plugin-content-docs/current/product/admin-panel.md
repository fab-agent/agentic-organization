---
id: admin-panel
title: User and Access Management
sidebar_label: User Management
---

# User and Access Management

fab.engineering uses an invitation-based user system. No one can self-register; all users are invited to the platform by admins through personnel records on the People page.

---

## User Creation Flow

### 1. Add an Email to the Personnel Record

Go to the **People** page. Open the relevant human personnel record, or fill in the **Email** field when creating a new record.

- The personnel type must be **Human** (invitations are not sent to Agent-type records).
- Personnel whose email field is filled in but who have not yet been invited will appear in the table with a **"Not invited"** label.

### 2. Send an Invitation

Click the envelope (mail) icon on the personnel row. A dialog titled **"Invite"** will open.

In the dialog:
1. Select a **Platform Role**: `founder`, `executive`, `dept_head`, `agent_owner`, or `user`.
2. Click the **"Send Invitation"** button.

The system performs the following in the background:
- Generates a 10-character temporary password in `XXXXX-XXXXX` format (uppercase letters + digits, valid for 30 minutes).
- Sends an invitation email to the selected email address via Resend. The temporary password is displayed in plain text in the email.
- Creates a user account and company membership in the database.
- Updates the row in the People table to **"Active"** (green, user icon).

### 3. User Completes First Login

The user navigates to `/login`, enters their email and temporary password. Because the system marks the password as `force_change`, they are automatically redirected to `/set-password`. The user sets a new permanent password and logs into the platform.

---

## Password Reset (Admin)

If a user forgets their password, there is no self-service reset. The admin follows these steps:

1. Go to the relevant personnel row on the People page.
2. Click the password reset button.
3. The system generates a new 30-minute temporary password and sends it to the user via email.
4. On their next login, the user is redirected to `/set-password`.

:::info
If the temporary password has expired and the user attempts to log in, the system automatically generates a new temporary password and immediately sends it to the user via email.
:::

---

## Role Management

A user's platform role is set at the time of invitation. To change a role, use the user membership editing interface on the People page.

For the role hierarchy and the access scope of each role → [Authentication and Roles](../platform/auth-and-roles.md)

---

## API Endpoints

Backend endpoints related to user management:

| Endpoint | Method | Description | Permission |
|---|---|---|---|
| `/auth/token` | POST | Login (email + password) | Public |
| `/auth/me` | GET | Logged-in user + memberships | Login required |
| `/auth/invite` | POST | Create user + send invitation email | `manager+` |
| `/auth/change-password` | POST | Change password (current password not required) | Login required |
| `/auth/reset/{user_id}` | POST | Admin password reset | `manager+` |
| `/personnel/{id}/invite` | POST | Direct invitation from personnel record | `manager+` |

For interactive API documentation, visit `http://localhost:8000/docs` (Swagger UI) while the platform is running.
