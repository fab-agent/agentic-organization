---
sidebar_position: 10
---

# Change Requests

The skills and permissions given to agents affect the company's risk. That is why an agent's configuration, skill or policy changes through **two-stage approval**. At the end of approval the change is applied and, if wished, written to Git.

**Where:** **Changes** (Department head and above).

## What is it used for?

| Type | What changes |
|---|---|
| **Agent configuration** (`agent_config`) | Name, title, department, model, status, owner, agent-specific skills |
| **Skill** (`skill`) | The content or setting of a company skill |
| **Policy** (`policy`) | The text of a policy |

A request is opened in these ways: the **Change Request** button on the **Agents** page (title, type and proposed values are entered); editing a record on the **Skills** and **Policies** pages and pressing **Submit for Approval**.

## Approval flow

```
submitted ──► dept_head_approved ──► committed
   │                  │
   └──────► rejected ◄┘
```

| Stage | Who | What they do |
|---|---|---|
| 1. Department approval | Department head or above | **Dept Approve** or **Reject** (optional note) |
| 2. Final approval | Executive or founder | **Admin Approve & Commit** or **Reject** |

The page has status filters: All, Pending, Dept Approved, Committed, Rejected. When you open a request you see the approval history, notes and the proposed change.

## Who may approve what?

- First approval: founder, executive or department head. A department head approves only targets in **their own department**.
- Final approval: only a company-wide executive or founder. The person who opened the request and the person who gave the first approval cannot give the final one; the requester cannot give the first approval of their own request either.
- The target (agent, skill, policy) must exist in the request's company; the proposed department and responsible person must belong to the same company.
- If two people approve at the same moment only one wins; the other gets `409`.
- A request is visible to its author, the approvers in scope (company-wide founder/executive/department head, or the head of the agent's department) and the agent's owner.

## What happens at final approval?

1. If a **Git connection** is defined for the company, the change is committed to the relevant file:
   - Agent configuration → `agents/<slug>/agent.yaml`
   - Skills → `agents/<slug>/skills.yaml`
   - Policy → `agents/<slug>/policy.yaml`

   The commit message carries the request title, type and request id; the commit link is written to the request.
2. If the commit succeeds, the change is **applied to the database** and the request becomes **committed**.
3. If there is **no** Git connection, the change is applied directly and the request still becomes **committed**.
4. If the commit **fails**, the approval is saved but the change is not applied; the error is written to the request's note. You need to fix the problem and try again (see [Settings → Git](/guide/settings#git-integration)).

:::info Supported Git system: GitHub
Change-request commits currently work only for **GitHub**. Managing company policies like a code repository with a local git system is **planned** work and does not exist yet; see [Developer Notes](/developer-notes/overview).
:::

:::info Direct edits
Agent settings (model, status, owner, skills, policy links) can be written directly through the API only by a company-wide founder or executive; a department head may only set up an agent that is still `draft`. For a live agent everyone opens a change request.
:::
