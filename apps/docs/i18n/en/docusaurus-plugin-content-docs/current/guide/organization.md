---
sidebar_position: 2
---

# Organization: Company, Department, Personnel

## Companies

One installation can hold several companies; each has independent department, personnel, agent and policy data. Switch between companies from the company box at the bottom left, and create a new one with **Add Company**. You edit company details (name, sector, website, vision, mission, values, goals) on the **Dashboard**; this information also goes into the agents' context.

## Departments

**Structure → Departments**. Departments form a tree: each department can belong to at most one parent department.

| Field | Description |
|---|---|
| Name | Required. Example: `Software Development` |
| Slug | Short name; generated from the name, can be edited by hand |
| Parent department | Leave empty to make it a root department |
| Description | The department's responsibility |
| Goals | One goal (OKR) per line |
| Policies | Policies that apply to agents in this department |
| Status | Active / Inactive |

Rules: a department cannot select itself as parent; choices that would create a cycle are excluded from the list. If a department is deleted its child units are not deleted; they become root departments.

Policies linked to a department become the default policies of the agents in that department ([Skills and Policies](/guide/skills-and-policies)).

## Personnel

**Structure → People**. Personnel covers both humans and agents; both sit in the same hierarchy.

| Field | Required | Description |
|---|---|---|
| Full name | Yes | |
| Slug | Yes | Generated automatically |
| Title | No | Displayed position |
| Role | No | Free-form role label (not the platform role) |
| Type | Yes | **Human** or **Agent** |
| Department | No | |
| Manager | No | Reporting hierarchy |
| Email | No | For human personnel; used for the platform invitation |

Giving platform access requires an [invitation](/guide/people-and-access). When a record of type agent is added, the agent configuration is opened automatically → [Agents](/guide/agents).

A deleted personnel record is removed permanently; for agents, **archiving** (making inactive) keeps the record.

## Organization chart

The **Organization** page offers two views:

- **Personnel:** shows every person and agent in a hierarchical tree. Humans and agents have different colors; clicking an agent card shows its model, skills, status and owner. There are zoom in, zoom out and reset buttons.
- **Department:** lists departments as a tree; roots can be collapsed and expanded, and each unit shows its number of humans and agents.
