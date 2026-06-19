---
sidebar_position: 1
---

# fab.engineering

**Self-hosted, open-source** platform for companies to manage AI agents in a structured way.

Assign an AI agent to every personnel member, manage policies and skills via YAML files, visualize the org chart. The platform offers invite-based user management and a role hierarchy for team-based access control.

---

## Core Concepts

| Concept | Description |
|---|---|
| **Company** | Top-level organizational unit. Multiple companies can be managed. |
| **Department** | Team/unit linked to a company. Carries goals and a policy list. |
| **Personnel** | Human employee or agent. Both appear in the same hierarchy. |
| **Agent** | AI configuration assigned to a personnel member (model + skills + status). |
| **Skill** | A capability definition for an agent (name, version, description). |
| **Platform User** | A human who logs in with email + password. Added via invite. |

---

## What Can You Do?

- Manage multiple companies from a single platform
- Build nested department hierarchies with `parent_id`; view them in the org chart
- Configure a unique AI agent for each personnel member
- Define model, skills, and policies per agent
- Sync all configuration to GitHub/GitLab/Gitea via YAML files
- Manage change requests with a two-stage approval flow (dept head → admin)
- Route tasks to the nearest matching agent
- Schedule autonomous flows with cron expressions
- Chat directly with agents in real time (SSE streaming)
- Delegate tasks between agents (A2A) with human approval
- Track all platform actions in the Audit Log

---

## What Is It Not?

- Not an LLM training platform — it manages existing agents, doesn't create new models
- Not a prompt-only chatbot — each agent has a role, department, skills, and organizational context
- Not SaaS — entirely self-hosted; your data stays on your own server

---

## Quick Start

→ [Installation](getting-started/installation)  
→ [User Roles](getting-started/user-roles)  
→ [Agent Usage Guide](getting-started/agent-usage)
