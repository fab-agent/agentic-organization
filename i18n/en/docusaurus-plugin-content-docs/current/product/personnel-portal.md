---
id: personnel-portal
title: People Page
sidebar_label: People
---

# People Page

The People page is the central hub for listing all human personnel belonging to a company and managing their platform access.

## Overview

The following operations are performed from the People page:

- Listing, adding, and editing human personnel for the company
- Assigning an email address to personnel
- Sending platform invitations and tracking access status
- Admin password reset

---

## Personnel Table

The table displays the following columns for each human personnel record:

| Column | Description |
|---|---|
| **Full Name** | The personnel's name and title |
| **Department** | The department they belong to |
| **Email** | The email address used for platform invitations |
| **Platform** | The status of the user account |

**The Platform column shows two states:**

- **Active** (green, with a user icon): The personnel has an active platform account.
- **Not invited** (with an envelope icon): The personnel has an email but no invitation has been sent yet.

For personnel without an email address, nothing is shown in the Platform column.

---

## Sending a Platform Invitation

To invite a personnel member to the platform:

1. Go to the **People** page and open the relevant personnel record (or enter an email when adding a new record).
2. Make sure the **Email** field is filled in.
3. Click the envelope (mail) icon in the table row.
4. The **"Invite"** dialog opens. Select the appropriate **Platform Role** for the user from the list:
   - `Kurucu (founder)`
   - `Yönetici (executive)`
   - `Bölüm Yöneticisi (dept_head)`
   - `Ajan Sorumlusu (agent_owner)`
   - `Kullanıcı (user)`
5. Click the **"Send Invitation"** button.

The system automatically:
- Generates a **temporary password valid for 30 minutes** in `XXXXX-XXXXX` format (uppercase letters + digits).
- Sends an invitation email to the personnel's address via Resend. The temporary password is included in plain text in the email.
- Creates a user account and company membership record in the database.
- Updates the table row to **"Active"**.

:::info
The invite button is only visible for personnel that meet all of the following conditions: Type = Human, Email is filled in, and no platform account exists yet.
:::

---

## Temporary Password Expiration

If the user does not log in within 30 minutes after the invitation is sent, the temporary password becomes invalid. When the user attempts to log in:

1. The system automatically generates a new temporary password.
2. An email containing the new password is immediately sent to the user.
3. The user can log in with the new password.

An Admin can also manually trigger a new temporary password by clicking the **Reset Password** button.

---

## First Login Flow (User Side)

1. The user receives the temporary password in their email.
2. They go to the `/login` page and enter their email and temporary password.
3. The system redirects them to the `/set-password` page.
4. The user enters and confirms their new permanent password, then saves it.
5. They are redirected to the home page and can now use the platform according to their role.

---

## Adding Personnel

When the **"New Personnel"** button is clicked, the form that opens contains the following required and optional fields:

| Field | Required | Description |
|---|---|---|
| Full Name | Yes | |
| Slug | Yes | Auto-generated, editable |
| Title | — | Displayed position |
| Type | Yes | **Human** or **Agent** |
| Department | — | Department to associate with |
| Manager | — | Reporting hierarchy |
| **Email** | — | For platform invitation; recommended for human-type personnel |

---

## Role Details

For the pages each role can access and what they can do → [User Roles](../getting-started/user-roles.md)  
For technical authentication documentation → [Authentication and Roles](../platform/auth-and-roles.md)
