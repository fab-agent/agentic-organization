# ADR-0005: Executable Policy Engine (fail-closed broker)

- **Status:** proposed
- **Date:** 2026-09-01
- **Related:** ADR-0003, ADR-0006, ADR-0010; block/buzz `crates/buzz-agent/src/permission.rs`

## Context and problem

Today `Policy` is just a markdown document; `build_system_prompt` adds the policy
**names** to the system prompt (`agent_runtime.py:82`). There is no mechanism that
stops a tool call. "Not being able to override policies" requires an executable
engine.

## Options considered

- **A — prompt only (today's approach).** If the model is persuaded, the policy
  collapses. Insufficient.
- **B — a rule DSL** (like buzz's `evalexpr` filter): sandboxed boolean
  expressions with a timeout, a size limit, and a circuit breaker.
- **C — embed an off-the-shelf policy engine** such as OPA/Rego or Cedar.
- **D — hybrid:** structured rules (source/tool/argument → allow|ask|deny) + a
  small sandboxed expression when needed; the markdown policy remains as the
  human-readable layer.

## Decision (proposed)

**D.** `backend/services/policy_engine.py`:

- **Input:** `PolicyDecisionRequest{ principal, tool, args, source_provenance,
  context }` (see ADR-0010 for provenance).
- **Rule model:** ordered rules; each has `match` (tool glob, argument patterns,
  provenance condition) + `effect` (`allow` | `ask` | `deny`) + `reason`. The last
  matching rule wins (consistent with opencode `permission` semantics).
- **Fail-closed:** rule evaluation error, unknown tool, malformed argument,
  timeout → `deny`. The buzz `PermissionDecision` pattern: "anything that is not a
  complete, well-formed allow is a deny".
- **For `bash`:** a glob deny-list is not enough (easily bypassed — `g""it`,
  `$(echo rm)`). The command AST is parsed; an allowlist-first approach. Details
  in a separate ADR.
- **Enforcement points (two-sided):**
  1. **Backend:** `agent_runtime.execute_skill` calls it before every tool call.
  2. **Laptop:** the opencode org plugin calls the gateway's `/policy/decide`
     endpoint inside `tool.execute.before`; `deny` → throw.
- **Sandboxed expression evaluation:** hard timeout (100ms), input size limit
  (4KB), restricted function set, rule disabled after N consecutive timeouts
  (the buzz `filter.rs` pattern).
- **Every decision** is written to the audit (ADR-0006): request, matched rule,
  effect.

## Open questions

- Rule authoring: a UI form, YAML, or both? Should automatic rule extraction from
  the markdown policy (via an LLM) be attempted?
- What does an `ask` decision map to on the laptop (an opencode approval prompt)
  and in the backend?
- The relationship with policy versioning + signing (ADR-0011).

## Consequences

- **Positive:** Real, testable enforcement. The `policy-engine.yml` CI catches
  regressions with a "fail-closed" check and a "these calls must be denied" golden
  set.
- **Negative / cost:** Rule authoring is a new operational burden. A wrong rule
  blocks the developer — a good error message and an `ask` escape hatch are
  essential.
