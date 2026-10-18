---
sidebar_position: 3
---

# People and Access

Nobody can register for the platform on their own. Every user is invited by a manager.

## Inviting

1. On **Structure → People**, open the person's record (the type must be **Human**) and fill in the **Email** field. People who have an email but have not been invited appear with the **Not invited** label.
2. Press the envelope icon on the row, choose a **platform role**, and press **Send Invite**.
3. The system generates a temporary password in the form `XXXXX-XXXXX` that is **valid for 30 minutes**, creates the user account and company membership, and sends the password to the person. The row becomes **Active**.

Delivery is by email (if Resend is configured) and by Telegram (if the company has a bot). If neither exists, the message is only written to the server log; in that case you have to take the temporary password from there.

## First sign-in

The person signs in on the `/login` page with the email and temporary password; the system automatically redirects them to the **set new password** page. If the password has expired, a new temporary password is generated and sent when they try to sign in.

## Forgotten password

There is no self-service reset and the interface has no "reset password" button. There are two ways:

- If the temporary password has expired, when the user tries to sign in the system **automatically generates and sends a new temporary password**.
- A manager can call `POST /auth/reset/{user_id}` through the API to send a new temporary password.

A signed-in user can change their own password on the **Profile** page (at least 8 characters). The Profile page also shows the companies you belong to and your role in each.

## Roles

A role is given **per company** (a person can have different roles in different companies). There are five roles:

| Role | In short | Seen in the sidebar |
|---|---|---|
| **Founder** `founder` | Full authority; can delete the company; manages users and Telegram | All |
| **Executive** `executive` | Close to the founder; accesses Settings; gives the final approval on change requests | All |
| **Department head** `dept_head` | Manages the structure; gives the first approval on change requests | Dashboard, Structure, Organization, Changes, Flows, Jobs, Delegation |
| **Agent owner** `agent_owner` | Works with the agents and flows they are responsible for | Dashboard, Flows, Jobs, Delegation |
| **User** `user` | Daily work: chat, task requests, delegation | Dashboard, Jobs, Delegation (+ Inbox at sign-in) |

Comparison:

| Action | User | Agent owner | Dept. head | Executive | Founder |
|---|:---:|:---:|:---:|:---:|:---:|
| Chat, task request, delegation | ✓ | ✓ | ✓ | ✓ | ✓ |
| Creating flows | | ✓ | ✓ | ✓ | ✓ |
| Structure, organization, invitations | | | ✓ | ✓ | ✓ |
| Change request, first approval | | | ✓ | ✓ | ✓ |
| Change request, final approval | | | | ✓ | ✓ |
| Settings (providers, Git, backup, databases…) | | | | ✓ | ✓ |
| Telegram settings, user management, deleting the company | | | | | ✓ |

:::caution Difference between the interface and the API
The table above describes what is **shown and doable in the interface**. On the API side, operations such as departments, personnel and flows only check company membership; a role check also exists in the API for these operations: updating company details (executive+), deleting the company (founder), user management and Telegram (founder), provider keys, and writing policies/skills/backup/databases (being at least a department head in some company). In a sensitive installation, restrict direct access to the API. See [Security](/technical/security).
:::

## Changing a role

A person's role is given when they are invited. Who may hand out which role is also enforced in the API (only company-wide memberships count):

| Role to grant | Who may grant it |
|---|---|
| Founder, executive | Founder |
| Department head | Founder, executive |
| Agent owner, user | Founder, executive, department head |

An unknown role returns `422`, an unauthorised grant `403`. An existing founder or executive membership cannot be lowered by an invite. To change a role, an authorised person invites the same email again with the new role (the existing membership is updated).
