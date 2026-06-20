# Agent Management

Agent Management covers the processes of defining, managing, and assigning agents within an organization.

## What Is an Agent?

An agent is an autonomous entity equipped with a specific model, skill set, and policy. Each agent is assigned to a personnel member and is used to reduce that person's workload.

## Agent Properties

| Property         | Description                                         |
|------------------|-----------------------------------------------------|
| Model            | The LLM to be used (Claude, GPT, Gemini, etc.)     |
| Skill Set        | The tools the agent can use                         |
| Policy Set       | The guardrails the agent must follow                |
| Personnel        | The employee the agent is linked to                 |
| Status           | active / draft / archived                           |

## Agent Creation Flow

1. The Admin navigates to the Agent Management screen.
2. Clicks the "New Agent" button.
3. Enters the agent name, model, and description.
4. Selects the relevant personnel.
5. Assigns Skills and Policies.
6. The agent is created and handed over to the personnel.

## Relationship Between Agent and Personnel

- An agent can be assigned to **only one personnel member** (MVP).
- Personnel use the agents assigned to them via the Personnel Portal.
- Skills developed by the agent are published with the personnel member's approval.

## Agent Statuses

| Status    | Meaning                                                     |
|-----------|-------------------------------------------------------------|
| Draft     | Not yet complete, in the testing phase                      |
| Active    | Ready for use, actively used by personnel                   |
| Archived  | Decommissioned, viewable only                               |

---

*This module is one of the core components of the Admin Panel.*
