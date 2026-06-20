---
id: github-integration
title: GitHub Integration
sidebar_label: GitHub Integration
---

# GitHub Integration

fab.engineering allows a GitHub organization to be connected per company. Once connected, approved Change Requests are automatically committed to that repository.

---

## Overview

| Feature | Description |
|---|---|
| Authentication | Personal Access Token (PAT) |
| Scope | Single GitHub org per company |
| Trigger | Admin-approved Change Request |
| Commit record | SHA and URL are stored in the request record |

---

## Setup

Go to the **Settings** (`/settings`) page and switch to the **Git Integration** tab.

### 1. Create a GitHub PAT

In your GitHub account, follow **Settings → Developer settings → Personal access tokens → Tokens (classic)**:

- **repo** permission (for private repositories) or **public_repo** permission (for public repositories only)
- Optional: set an expiration date

:::caution
The token credentials provide full access to repository content. Use the token exclusively for the fab.engineering integration and do not share it with anyone.
:::

### 2. Enter Connection Details

Fill in the following fields in the Settings — Git Integration form:

| Field | Description | Example |
|---|---|---|
| **GitHub Org / User** | GitHub organization or username | `my-company` |
| **Repo Name** | Target repository name | `agent-configs` |
| **Branch** | Branch to commit to | `main` |
| **GitHub PAT** | Personal Access Token | `ghp_...` |

Click the **Connect** button. The system validates the token without making a test commit.

### 3. Test the Connection

Once connected, a **Test** button appears. This button:
- Verifies that the repository is accessible using the provided token.
- Displays the result instantly on screen (`Connected` / `Error`).

---

## Sync Log

The Settings — Git Integration page includes a **Sync Log** table listing recent commit operations. Each row shows:

- Commit date/time
- Commit SHA (clickable link to GitHub)
- Operation result (`success` / `error`)
- Short error message if applicable

---

## Commit Flow

When a Change Request is approved by an Admin:

```
Admin "Approve & Commit" → backend commit flow
    ↓
Repository contents fetched via GitHub API
    ↓
Agent configuration file updated
    ↓
Updated file pushed to GitHub
    ↓
SHA and commit URL written to the ChangeRequest record
    ↓
"Commit successful" notification appears in Inbox
```

---

## Disconnecting

The **Disconnect** button on the Settings — Git Integration page:
- Deletes the GitHub configuration (including the PAT).
- Does not affect SHA records on existing Change Requests.
- Future Admin approvals will complete without the commit step.

---

## Common Issues

| Issue | Possible Cause | Solution |
|---|---|---|
| `401 Unauthorized` | PAT has expired | Generate a new token and reconnect |
| `404 Not Found` | Incorrect repo name or org name | Check the settings |
| `403 Forbidden` | Token missing repo permission | Select the `repo` scope when creating the PAT |
| Commit fails, no log visible | Branch is protected | Disable the branch protection rule or grant permission to the bot user |

---

## API Endpoints

| Endpoint | Method | Description | Permission |
|---|---|---|---|
| `/git/config?company_id=` | GET | Retrieve current Git configuration | `executive+` |
| `/git/config` | POST | Save / update configuration | `executive+` |
| `/git/config?company_id=` | DELETE | Delete configuration | `executive+` |
| `/git/test?company_id=` | POST | Test connection | `executive+` |
| `/git/logs?company_id=` | GET | List sync logs | `executive+` |
