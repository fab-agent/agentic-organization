# ADR-0022: Herdr for power users, a minimal web view for departments, and an approved learning loop

- **Status:** accepted
- **Date:** 2026-10-17
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0001, ADR-0002, ADR-0005, ADR-0006, ADR-0010, ADR-0014 (decisions 2 and 4 superseded here), ADR-0016, ADR-0017, ADR-0018, ADR-0019 (§5 narrowed, §8 changed here), ADR-0021

## Context and problem

1. **Two kinds of users, and the web UI serves neither well.** The SvelteKit
   frontend exposes the whole company model — agents, skills, policies, flows,
   change requests, org chart. Power users work in a terminal anyway; accounting,
   finance and HR staff only need to talk to their assistant, send files, watch it
   work and collect the result. For them the current UI is too much, and showing
   everyone every skill and policy is more disclosure than the work needs.
2. **We do not need to build a terminal client.** ADR-0014 chose our own Rust
   binary (`packages/tui`, `fab`) and rejected "ship on top of herdr". Since then
   the herdr community plugin (`fab-agent/community`) shipped, and the org sidebar
   / approvals / file panes are small enough to be a plugin. Maintaining a
   PTY/pane engine is not where our value is.
3. **The company should learn from its own work.** Feedback and finished work are
   collected but change nothing. Google Research's `harness2` shows a method for
   improving the non-weight parts of an agent (system prompt, guardrails, memory,
   tool guidance, subagents, skills, scripts, plugins): propose edits, test them,
   keep what helps, carry lessons forward. It is a research release (Apache-2.0,
   "not an officially supported Google product"; its executors have unrestricted
   network access), so it informs the design but is not a production dependency.
   A local run of `harness2-demo` showed it stores the harness as plain files
   (`systemprompt.md`, `guardrails.md`, `LongTermMEMORY.md`, tool guidance,
   scripts) plus per-task runs, which maps onto our versioned config.

**Review finding that shapes this ADR.** The existing change-request flow is not a
security boundary today: `backend/api/change_requests.py` authenticates the caller
(`get_current_user`) but never checks company membership, role or object
ownership, lets the same user perform both approval stages, and takes `company_id`
for the admin stage from the request. It only knows `agent_config`, `skill` and
`policy`; a `harness` type would be accepted by the schema but not committed or
applied. "Learning proposes, a human approves" therefore depends on fixing the
approval path first (decision 1).

> **Note (2026-10-18, acceptance review):** the review findings quoted in the context (change requests did not check membership, free-form harness strings) were true when written and were fixed on 2026-10-17: change requests now check company, role and scope and the `change_type` set is closed. The learning loop, probe environment, local helper and the department web view are still gated follow-ups, not shipped.

## Options considered

**Client:** A — keep our own Rust `fab` binary (ADR-0014). B — stock herdr plus
our plugin for power users, minimal web view for departments. C — keep the full
SvelteKit UI for everyone.

**Learning:** D — depend on harness2 directly. E — adopt its method in our own
service, every adopted change going through human approval. F — automatic
self-modification.

## Decision

**B + E**, with these decisions.

### 1. Approval path is fixed before anything is learned (precondition)

Learning-loop proposals must not ship until the change-request path enforces:
company membership and object ownership on every read/write (deny by default,
also for the existing endpoints); stage 1 by a department head **of the target's
department**, stage 2 by a company-level approver; proposer ≠ approver and the two
approvers are different people; the repository/config is selected from the stored
`cr.company_id`, never from the request. Negative-authorisation tests cover
cross-company access, wrong role, and the same person approving twice.

### 2. Harness changes are typed artifacts, not free strings

A `harness` change request carries a target (person / department / company), a
base version, a typed artifact and a content hash. Mutable fields are an
allowlist: prompt text, memory entries, tool *guidance* (descriptions), and
skill *instructions*. **Never mutable by the loop:** policy rules and precedence,
tool ACLs, identity and token scopes, egress, approval gates, data-sharing limits,
and any executable code (scripts, plugins, skill code). Guardrails that enforce
policy are policy, not advice; those that are advisory text are tagged as such at
creation, and only the tagged ones are learnable. Changes to non-learnable fields
follow the human-authored path (ADR-0017). Approval binds to the candidate hash +
base version + evidence; if base or candidate changes, it is probed and approved
again. Approval, durable storage and activation are separate success states;
unsupported types or missing storage fail closed. Activation is atomic and
idempotent per tenant, running sessions finish on the version they started with,
and each run records the harness version it used. Rollback restores the previous
configuration; it does not undo external side effects of earlier runs.

### 3. Learning sources and privacy inheritance

ADR-0019 §5 allowed learning only from a person's own messages and corrections.
This ADR narrows the loop to the same principle: the loop learns from
**verified human signals** — explicit corrections, thumbs/comments, resolved
contests, outcomes decided by a reviewer. Task content, tool results and
documents are **evaluation data only**; they are never copied into a lesson or
memory entry. Each lesson/diff records its source, owner, scope and the
human-confirmed intent. Personal sources (ADR-0021 shadow ratings, contest notes,
review data) never become company memory directly; promoting a person-scoped
lesson to department/company scope is a separate reviewed step. The loop obeys the
review opt-in, shadow period, group floor, contest/withdrawal and erasure rules of
ADR-0021: with review off it produces and uses nothing; a withdrawn or contested
rating is excluded; erasing a person removes their derived evidence from the
replay set and from pending proposals, and personal data is not embedded in
immutable Git/audit entries (only references). Redaction is not anonymisation and
is not treated as such.

### 4. Poisoning and judge integrity

Signals are deduplicated, capped per person, and need a minimum number of
independent sources before a pattern is proposed. The judge is separate and
low-privilege; a candidate cannot change its own test, criterion or baseline. Probe
sets include a hidden holdout, security-regression tasks and injection samples;
failed or unclear probes are not adopted; insufficient history keeps adoption
**closed**. ADR-0021's group floor is a privacy control, not an anti-poisoning
control, and is not relied on as one. The proposer has no access to production
memory, tools, or the approval/activation APIs. "Measured effect" has a defined
metric, threshold, cost/latency ceiling and a security veto, set at installation.

### 5. Probe environment

A dedicated ephemeral profile, narrower than the ADR-0002 sandbox: no production
credentials or tokens, no host/home/Docker socket, no production workspace or
shared writable cache; redacted fixtures mounted read-only; writes to a
throwaway area; non-root, dropped capabilities, CPU/RAM/disk/time/process
budgets; all MCP and side-effect tools are fixtures or mocks; no network except a
probe-only model path (or a local model). Probe output and judge evidence are
untrusted, ACL-scoped data.

### 6. Power users: herdr plus our plugin

Stock herdr (a fork only if a patch is unavoidable) with our plugin on top of the
community chat. `packages/tui` is frozen. This supersedes ADR-0014 decision 2 and
the "no chat / no new web features" part of decision 4; server-side workspaces
(decision 1) stand. Migration conditions, taken from the spike requirements:
herdr version pinned with a defined update source, a full-version licence review,
plugin permissions listed, and acceptance tests showing no gateway/policy/audit
bypass, per-person workspace isolation, token revocation and signed-command
verification.

### 7. Departments: a minimal route group in the SvelteKit app

Role `assistant_user`; a few components, no new framework. Feature matrix:

| Feature | assistant_user |
|---|---|
| Chat, file upload, outputs list/download | yes |
| Task status stream | yes, see below |
| "My context": connected tools, own team / manager / colleagues (name, role, department only — an allowlisted projection, never the full personnel record), applicable role policies, mission / vision / goals | yes, read-only |
| My review, rating contest/withdraw, shadow visibility, learned items about me (review / revert), refusal → propose-change | yes (ADR-0019/0021 person rights are kept) |
| Approving team changes | only if the person also holds a manager role, in that role's view |
| Agent / skill / policy editing, company-wide lists | no |

Scoping is enforced in the API per caller (object-level checks), never only in the UI.

**The stream carries user-facing status events, not raw reasoning.** Events are
generated from allowlisted fields (step, tool name, short outcome); raw model
reasoning, system prompts and raw tool arguments/results are not streamed. The full
event is checked and, if needed, suppressed before sending; source ACLs of tool
results are preserved. Reconnect/replay, output download and any signed URL
re-check company/person/run authorisation and honour revocation; logs, errors and
caches follow the same boundary.

### 8. The local "Assistant" folder (Windows and macOS)

Changes ADR-0019 §8 (no automatic `in/` upload, no automatic summary sync): the
platform syncs nothing automatically. The person's own files and second brain live
in the folder. Access is through the **herdr plugin / a local helper chosen in the
plugin spec**, not the browser; the browser path uses explicit file upload only.
Required: explicit file selection and a transfer preview; canonical-path checks
that reject symlinks, junctions, reparse points and path traversal (and re-check at
open time); a folder owned by one OS user; safe download (no overwrite, no
auto-open, macro/script files flagged). The platform cannot prevent OS or
third-party sync (iCloud/OneDrive), and says so. Disk encryption is a deployment
requirement but does not address unlocked-session malware.

### 9. Data retention

Transcripts, status events and outputs live in the audit/eval log (ADR-0006) for a
per-company retention period set at installation (ADR-0016). Replay, lessons and CR
evidence use only entries inside it; erasure follows decision 3. The number of days
is a deployment parameter.

### 10. Eval/config layer ownership

The authoritative configuration and eval-log store is owned by the installation
kit (ADR-0016). It must define: replay schema and data class; the run / policy /
model / harness / fixture versions recorded for each run; and the eval budget.
Whether it exists in a separate installer repository is **unverified from this
repo** and is the first follow-up.

### 11. Out of scope for v1

No automatic activation of any harness change; no learning from policy or
permission edits; no cross-company learning or shared harness store; no server-side
sync or backup of the local Assistant folder; no editing of agents, skills or
policies in the department view; no new observability product built by us (a
viewer such as Langfuse or Phoenix is a separate decision); no per-token cost
optimisation in the loop.

## Consequences

- **Positive:** less UI to build and secure; a least-disclosure surface for
  departments; the loop reuses approval, audit and redaction, and fixing the
  approval path improves the platform regardless of this ADR.
- **Negative / cost:** the approval-path fix, a typed harness artifact and a
  dedicated probe profile must exist before any learning ships; dependence on
  herdr's plugin API and cadence; two surfaces to support; replay needs enough
  clean history, so the loop stays off at first.
- **Accepted residual risk:** a plausible but wrong, allowlisted change (prompt,
  memory, tool guidance) can still pass human approval; evidence, hash binding and
  rollback limit it. Raw content may still appear in outputs the person downloads.
- **Follow-ups:**
  1. Fix and test the change-request authorisation path (decision 1) — a
     standalone security fix that should not wait for this ADR.
  2. Locate or define the config/eval-log layer and the replay format (decision 10).
  3. Typed `harness` artifact and target model (decision 2).
  4. `assistant_user` role, the scoped context endpoint, and the status-event stream.
  5. Plugin spec for herdr and the Assistant-folder helper; licence and version pin.
  6. Mark ADR-0014 decisions 2 and 4 and ADR-0019 §5/§8 as superseded once accepted.
