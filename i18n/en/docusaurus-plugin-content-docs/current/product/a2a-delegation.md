---
sidebar_position: 4
---

# Agent-to-Agent (A2A) Delegation

An agent can delegate work it cannot do to another agent during a conversation. This mechanism is called **Agent-to-Agent Delegation** (A2A).

---

## When to Use It

| Scenario | Delegation Flow |
|---|---|
| InstaCraft can't generate visuals | InstaCraft → PostMediaAgent |
| LinkMind can't write code | LinkMind → CodeGuard |
| SupportBot can't answer finance questions | SupportBot → LedgerAI |
| Any agent → task requiring specialized expertise | Requesting Agent → Specialist Agent |

---

## How It Works

```
User → Requesting Agent
           │
           ├─ [calls the delegate_to_agent tool]
           │    to_agent_slug: "postmediaagent"
           │    task: "Generate a LinkedIn cover image"
           │    context: "Blue tones, modern style..."
           │
           ▼
     A2A Request created (pending_approval)
           │
           ▼
     Notification to responsible person → Telegram /approvals or A2A page
           │
           ├─ ✅ Approved → Target Agent runs
           │                  │
           │                  ▼
           │            Result → pending_result_approval
           │                  │
           │                  ▼
           │            Second approval (accept the result)
           │                  │
           │                  ▼
           │            Result returned to Requesting Agent
           │
           └─ ❌ Rejected → Request is cancelled
```

---

## Setup — Step by Step

### 1. Which agents need the skill?

The `delegate_to_agent` skill should only be added to agents that will **initiate** delegations.  
The agent *receiving* the delegation (e.g. PostMediaAgent) does not need this skill.

**Example:** If InstaCraft will delegate visual work to PostMediaAgent → the skill is added only to InstaCraft.

---

### 2. Adding the Skill via UI

Go to the **Agents** page → select the relevant agent → click **Add Skill**:

```
Name:        delegate_to_agent          (must be exactly this name)
Version:     1.0
Description: Delegate tasks you can't do to another agent
Type:        Built-in
Function:    Agent Delegation
```

> **Important:** The name field must be `delegate_to_agent` (underscore, not space). The system matches by this exact name.

---

### 3. Finding Target Agent Slugs

You can see agent slugs on the **Personnel** page or in the agent profile. Example slugs:

| Agent Name | Slug |
|---|---|
| PostMediaAgent | `postmediaagent` |
| CodeGuard | `codeguard` |
| LedgerAI | `ledgerai` |
| LinkMind | `linkmind` |

Slugs are lowercase with no spaces. They are automatically determined when an agent is created in the system.

---

### 4. Teaching the Agent Who It Can Delegate To (Optional)

An agent can learn which slugs it can delegate to through its system prompt or a policy.  
Via **Add Policy → Scope: Agent**, you can define a rule like this:

```markdown
# Delegation Policy

## Task Routing
- Visual generation requests → `postmediaagent`
- Code review requests → `codeguard`
- Finance questions → `ledgerai`

## Rule
Delegate tasks you cannot do to the agents listed above.
Use the `delegate_to_agent` tool for delegation.
```

---

## Real Scenario: InstaCraft → PostMediaAgent

**User message:**
> "We need a LinkedIn cover image for Fabrika Software."

**InstaCraft's internal call** (not visible to the user):
```json
{
  "tool": "delegate_to_agent",
  "to_agent_slug": "postmediaagent",
  "task": "Create a professional LinkedIn cover image for Fabrika Software.",
  "context": "Modern, blue tones. Company name should be visible."
}
```

**InstaCraft's response to the user:**
> "I've created a request to PostMediaAgent for the visual. Waiting for your approval."

**You:** On Telegram: `/approvals` → press the **✅ Approve** button  
**Result:** PostMediaAgent generates the visual, result appears on the A2A page.

---

## A2A Statuses

| Status | Meaning |
|---|---|
| `pending_approval` | Awaiting initial approval |
| `approved` | Approved, target agent is starting |
| `running` | Target agent is executing the task |
| `pending_result_approval` | Awaiting result approval |
| `completed` | Entire process completed |
| `rejected` | Rejected |

---

## Telegram Integration

When a new delegation request is created, use the `/approvals` command via **@fablimitedBot**:

```
/approvals

📋 Pending Approvals

🤝 [A2A] LinkedIn cover image
  [✅ Approve]  [❌ Reject]
```

Just press the button — no need to log into the system separately.

---

## Frequently Asked Questions

**Why not add it to all agents automatically?**  
If every agent can delegate everything, you lose control. Consciously designing which agent can delegate to whom is good governance practice.

**What if the agent delegated to the wrong agent?**  
You can reject it at the approval stage. You can write a reason for the rejection; in the future the agent learns from this (with memory).

**Can it work without approval?**  
Currently no — all A2A requests require approval. This is an intentional design decision: as agent autonomy increases, human oversight is preserved.

**Is result approval also required?**  
Yes, it's two-stage: you approve the task → the agent runs → you approve the result. At the second approval you can see the result and reject it if insufficient.
