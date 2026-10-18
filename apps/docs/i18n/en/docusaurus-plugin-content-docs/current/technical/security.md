---
sidebar_position: 4
---

# Security

This page openly describes the web platform's security features and its **known limits**. The security of the developer workstation layer (gateway, policy engine, audit chain) is separate: [Developer Workstation](/workstation/overview).

## Authentication

- **Invitation-based:** there is no self-registration. Only while the database is empty does the first-setup page work.
- **Passwords** are hashed with bcrypt. A temporary password is valid for 30 minutes and must be changed at first sign-in.
- **Sessions** use JWT (HS256); token lifetime is 72 hours. With `ENVIRONMENT=production` the application **refuses to start** with a weak or placeholder `JWT_SECRET`.
- Nginx applies rate limiting to the login page.

## Storage of secrets

Provider keys, Git and Telegram tokens, the backup secret key and database connection strings are stored **encrypted with Fernet**; the APIs do not return them. The encryption key is in `data/.secret` (generated automatically on first run, permission `600`). **This file must be stored together with the database backup**; if it is lost, encrypted records cannot be decrypted.

:::note
The `ENCRYPTION_KEY` variable in `.env.example` is not read by the code; it does not determine the encryption key.
:::

## Authorization: what you need to know

- **Company isolation:** for company-bound data, the user must be a member of that company.
- **Role checks are partly in the interface only.** The interface hides menus and buttons by role; in the API many operations such as departments, personnel, flows and agents only check company membership. Roles are required in the API for: updating company details (executive+), deleting the company and managing users/Telegram (founder), and operations protected with `require_manager` (provider keys, writing policies/skills, backup, database connections, the policy engine mode). `require_manager` checks that the user is at least a department head in **any company**, not in that one.
- Consequence: a low-privilege member may be able to perform some operations they cannot see in the interface by calling the API directly. In sensitive environments, restrict access to the API at the network level and follow this in the improvement list in [Developer Notes](/developer-notes/known-limits).

## Limiting agent actions

- Every tool call passes through the policy engine (`dry_run` default; enforced with `enforce`). See [Policy Engine](/workstation/policy-engine).
- The database skill runs only `SELECT`; still, give a read-only database user.
- The `function` skill is not fully isolated ([Skill Types](/technical/skill-types#function)).
- Agent changes (configuration, skill, policy) go through two-stage approval and both are written to the audit log.
- Handing tasks between agents needs two human approvals.

## CORS and network

Allowed origins come from `CORS_ORIGINS` or `APP_URL`; `*` is not used together with credentials. In production only 80/443 should be open to the outside.
