# ADR-0003: Threat model and enforcement boundaries

- **Status:** proposed
- **Date:** 2026-09-01
- **Related:** ADR-0001, ADR-0002, ADR-0004, ADR-0006, ADR-0010

## Context and problem

The product claim: "employees cannot override policies, everything is logged."
But per ADR-0001 (opencode) + ADR-0002 (laptop execution), the agent runs **on
the user's machine, with the user's privileges**. This ADR states plainly which
guarantee is real and which risk is accepted — marketing and customer
expectations will rest on it.

## Actors and threats

| Actor | Threat |
|-------|--------|
| Prompt injection (web content, files, email, A2A output) | Tricking the agent into an unauthorised tool call / data exfiltration |
| Faulty agent behaviour | Accidental destructive command, push to the wrong repo |
| Curious employee | Probing/testing the policy boundaries |
| Determined malicious employee | Deliberately bypassing controls |
| Compromised workstation | Token/session theft |

## Enforcement layers and strength

1. **LLM Gateway (ADR-0004) — HARD.** All model traffic goes through it; it is
   logged server-side, where the user cannot alter it. Quota / model allowlist are
   enforced here. If the gateway is unreachable, the agent does not run.
2. **Audit chain (ADR-0006) — HARD (server side).** Hash-chained, append-only. The
   laptop can only write; it cannot delete or modify.
3. **Sandbox (ADR-0002) — MEDIUM.** Confines the accidental/injection blast radius
   to the container. Container escape / bypassing `3pa` is possible.
4. **opencode plugin + Policy Engine (ADR-0005) — SOFT.** The user can remove the
   plugin, edit the binary, or bypass the managed config with env vars like
   `OPENCODE_PERMISSION` (opencode issues #22292, #6358). It provides deterrence +
   observability, not cryptographic enforcement.

## Decision (proposed)

- The "policies cannot be overridden" claim is scoped to the **gateway + audit**
  layers; this is stated clearly in customer documentation.
- For developer personas, plugin-level policy is accepted as a **soft control**
  (the developer already has a shell — the threat model is set accordingly).
- For organisations that need hard enforcement, **server-side execution**
  (ADR-0002 option B) is offered as an optional deployment model in the future —
  a separate ADR.
- Detection-oriented controls: anomalies at the gateway (sudden token spike,
  off-allowlist host attempt), loss of plugin heartbeat in the audit → alert.

## Open questions

- Should the gateway automatically revoke a persona token when the plugin
  heartbeat is lost?
- How is sandbox integrity attested (should a signed image digest be reported to
  the gateway)?
- Raw prompt/response retention: on or off by default, and the KVKK/GDPR impact?

## Consequences

- **Positive:** An honest, defensible security posture. No false promises to
  customers.
- **Negative:** For a customer who wants "full enforcement", today's answer is
  "server-side execution is on the roadmap" — a competitive gap.
