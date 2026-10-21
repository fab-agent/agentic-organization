# ADR-0025: Odoo add-on — agents in Discuss, acting as the requesting user

- **Status:** proposed
- **Date:** 2026-10-21
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0004, ADR-0005, ADR-0006, ADR-0010, ADR-0019, ADR-0023

## Context and problem

Odoo 20 no longer offers a vendor-neutral AI layer; companies that run Odoo are tied to
Odoo's own AI offering. We want a company running Odoo (Community or Enterprise,
self-hosted) to get personas, guardrails, audit and **any model, including local ones**,
using the parts of agentic-organization that already exist: the LLM Gateway (ADR-0004),
the policy engine (ADR-0005), the hash-chained audit (ADR-0006) and one agent per
person (ADR-0019).

Two constraints shape the design. Odoo Enterprise and Odoo Online are priced **per user**,
and a service user created for API access counts as a user; one bot `res.users` per
persona would add seats. Odoo Online also restricts external API access by plan.

## Options considered

- **A — one bot `res.users` per persona, calling Odoo over its external API.** Simple
  ACLs, but adds seats on Enterprise and depends on external API availability.
- **B — one shared service user with broad rights, policy engine does all gating.**
  Breaks Odoo's record rules; a policy bug becomes a data leak.
- **C — persona as `res.partner`, tools executed in-process as the requesting user.**
  No seats, no external API, Odoo ACL and record rules stay in force.

## Decision

**C.** An `odoo-agentic` add-on (separate repo, separate licence; talks to
agentic-organization over HTTP only) with these parts:

1. **Persona = `res.partner`** shown in Discuss like OdooBot. Direct messages with a
   persona create chat sessions; channels may have a persona as a bot member
   (bot channels). No form-view buttons; Discuss is the only surface.
2. **Tool endpoint in the add-on.** The agentic-org backend calls back into a signed
   Odoo controller. The controller runs the tool with `env.with_user(requesting_user)`,
   so Odoo ACL and record rules apply to the agent exactly as to the human.
3. **Tool registry.** Each tool is a declared (model, method, argument schema) tuple.
   No raw SQL, no generic `execute_kw`. The existing ERP SQL skill is not used.
4. **Policy engine as the second lock.** `allow / ask / deny` per tool and per
   argument (model, field, amount threshold). Policy may only narrow what Odoo ACL
   already allows. `ask` becomes an activity / approval prompt in Discuss.
5. **Audit.** Every tool call is hash-chained in the backend audit with the
   record "agent Y on behalf of user X", and mirrored to the record's chatter.
6. **Provenance.** Text read from Odoo records (mail, notes, partner comments) is
   marked untrusted for ADR-0010 injection defense.
7. **Settings.** Gateway URL, persona↔partner mapping, policy set, signing secret.

## Consequences

- **Positive:** model-agnostic and local-capable; no extra Odoo seats; no dependence on
  Odoo's external API; Odoo permissions are not duplicated or bypassed.
- **Negative / cost:** the add-on must be maintained per Odoo major version; tool
  registry must be written per business flow.
- **Accepted residual risk:** local models make weaker tool calls, especially in Turkish
  and over many steps; policy and approval bound the damage but do not fix quality.
  Odoo licence terms on agent use were not verified for Enterprise; check before selling.
- **Follow-ups:** PoC on the Gündoğdu demo DB (cooling accounts: find, open a call
  activity, draft a quotation) with a cloud model vs a local model; licence text for the
  add-on repo; decide tool-call transport (HTTP callback vs MCP) after the PoC.
