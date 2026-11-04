---
sidebar_position: 3
---

# Executable Policy Engine

> ADR-0005 · `backend/services/policy_engine.py`,
> `backend/services/command_parser.py`

Policies in the web interface are Markdown documents; only their **names** enter the agent's instruction, and the model interprets them as guidance. The execution layer adds to this a second gate that **runs before the tool call**: the policy engine sees a command, gives `allow` / `ask` / `deny` according to the rules, and in `enforce` mode actually stops the call.

---

## Two functions

| Function | What it does |
|---|---|
| `evaluate(...)` | Pure, no side effects. Rule list + request → verdict. **Fail-closed:** `deny` on a parse/match error. |
| `decide(...)` | Wraps `evaluate()`; collects rules from the DB by resolving the scope, applies the rollout mode, writes the result to the audit. |

The opencode plugin calls `POST /policy/decide` in the `tool.execute.before` hook; in `enforce` mode, if `deny`/`ask` comes back the plugin **throws an exception** and opencode reports that the tool failed.

---

## Scope resolution

Starting from the persona, rules are collected in this order and **the most specific wins**:

```
company  →  department(s)  →  agent
```

Parent-department policies are **inherited** by child departments (`_department_chain`: walks up the `parent_id` chain).

---

## Rollout modes

The `PolicyConfig` table keeps a mode per scope (`company` / `department` / `agent`). The most specific `PolicyConfig` wins; if there is none, the default is `dry_run`.

| Mode | Behavior |
|---|---|
| `off` | The policy engine is skipped |
| `dry_run` | Evaluated and **written to the audit**, but the call is not blocked (default) |
| `enforce` | A `deny`/`ask` verdict stops the call |

**Exception:** fail-closed verdicts (the rule could not be parsed, the engine raised an error) block **in every mode except `off`**, including `dry_run`.

### Server-side policy gate (ADR-0026)

Every tool call on the backend passes one gate (`agent_runtime.policy_gate`): backend agent tools, flow tools, MCP `org_policies` and `/policy/decide`. The gate **fails closed**: an engine error, an unreadable policy, an unknown persona or a **decision that cannot be written to the audit chain** blocks the call (in every mode except `off`). A resolution error returns HTTP `503 policy_unavailable`.

Executable blocks in a policy body are strict: an unterminated block, one that does not parse, or one whose rules have the wrong shape is refused at save time with `422 malformed_policy`; if a stored policy breaks later, every decision for the people it applies to is denied. Contract: `docs/architecture/policy-block-contract.md`.

**Upgrade note:** before upgrading an existing install run `scripts/policy_inventory.py`; a policy that no longer parses, or an audit chain that cannot be written, now blocks tool calls.

**Still open:** policy change requests are validated but not applied to the Policy table; some backend chat paths call provider SDKs outside the shared gateway layer.

`resolve_mode(...)` returns the effective mode; `3pa policy` shows this and the effective rule list.

---

## Command matching

Bash commands are parsed into an **AST** in `command_parser.py` with [`bashlex`](https://github.com/idank/bashlex). When a rule says `rm -rf /`, string evasions such as `rm  -rf  /`, `rm --recursive --force /` and `/bin/rm -rf /` are also caught.

```
{ "match": "command", "command": "rm", "args_contain": ["-rf", "/"], "effect": "deny" }
```

A command that cannot be parsed → fail-closed → `deny`.

---

## Base rules

Even if nothing is configured, the engine comes with a set of **destructive command** base rules (disk wiping, fork bombs, reading credential files, `curl | sh` patterns). They produce a warning in `dry_run` and block in `enforce`.

---

## Where it connects

- The opencode plugin → `POST /policy/decide` (workstation)
- `agent_runtime.execute_skill()` → the same engine for agents in the web interface
- `3pa policy` → a preview of the effective rules for a persona
- ADR-0013 severity scoring → an accumulation of high-severity events can automatically move `PolicyConfig` to `enforce`

---

## Open items

- A frontend interface for writing rules (currently rules are JSON).
- An operator screen for `PolicyConfig` reset / mode switching.
