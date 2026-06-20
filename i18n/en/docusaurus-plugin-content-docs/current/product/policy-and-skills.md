# Policy & Skills

This module manages Policies that control agent behavior and Skills that agents can use.

## Policy (Guardrail)

Policies are guardrails that ensure agents comply with specific rules.

### Policy Types

| Type             | Description                                        | Example |
|------------------|----------------------------------------------------|---------|
| Content          | Content restrictions                               | Preventing sensitive data sharing |
| Behavior         | Behavioral rules                                   | Always responding in a polite and professional manner |
| Access           | Access restrictions                                | Access limited to specific department data |

### Creating a Policy

From the Policy Management screen, an Admin:
- Selects a policy name and department
- Defines guardrail rules in JSON format
- Sets the policy type
- Creates the policy

Created policies can be assigned to agents.

## Skill

Skills are tools that allow agents to interact with the outside world.

### Skill Types

| Type             | Description                                        |
|------------------|----------------------------------------------------|
| Function         | Functions defined in code                          |
| MCP              | Model Context Protocol tools                       |
| Custom           | User-defined custom tools                          |

### Skill Development Flow

1. Personnel develops a new skill through the Personnel Portal.
2. They test the skill.
3. They submit a publish request to the Admin.
4. The Admin reviews the request from the MCP Tool Requests screen.
5. Approved skills are added to the system and can be assigned to agents.

### Relationship Between Skills and Policies

- Both skills and policies can be assigned to an agent.
- Policies can also restrict skill usage.
- For example: "This skill can only be used by agents that have the following policies."

---

*Policy and Skill management ensures that agents operate safely and in a controlled manner.*
