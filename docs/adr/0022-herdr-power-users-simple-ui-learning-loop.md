# ADR-0022: Herdr for power users, a minimal web view for departments, and an approved learning loop

- **Status:** proposed
- **Date:** 2026-10-17
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0001, ADR-0002, ADR-0005, ADR-0006, ADR-0014 (client decision superseded here), ADR-0016, ADR-0018, ADR-0019, ADR-0021

## Context and problem

Three things have changed since ADR-0014.

1. **Two kinds of users, and the web UI serves neither well.** The SvelteKit
   frontend exposes the whole company model — agents, skills, policies, flows,
   change requests, org chart. Power users work in a terminal anyway; accounting,
   finance and HR staff only need to talk to their assistant, send files, watch it
   reason and collect the result. For them the current UI is too much, and showing
   everyone every skill and policy is also more disclosure than the work needs.
2. **We do not need to build a terminal client.** ADR-0014 chose our own Rust
   binary (`packages/tui`, `fab`) and rejected "ship on top of herdr" because a
   third-party plugin API would cap the product. Since then the herdr community
   plugin (`fab-agent/community`, v0.5.x) has shipped with signed messaging and
   server agents, and the org sidebar / approvals / file panes that justified the
   own binary are now small enough to be a plugin. Maintaining a PTY/pane engine
   is not where our value is.
3. **The company should learn from its own work.** Feedback (ADR-0021 ratings and
   contests, work review, thumbs on answers) and finished work are collected but
   change nothing. Google Research's `harness2` shows a way to improve the
   non-weight parts of an agent — system prompt, guardrails, memory, tool
   guidance, subagents, skills, scripts, plugins — by proposing edits, testing
   them and keeping the ones that help, carrying lessons to later tasks.
   It is a research release (Apache-2.0, few commits, "not an officially
   supported Google product"), and its executors run with unrestricted network
   access, so it can inform the design but cannot be a production dependency.

## Options considered

**Client**
- **A —** keep our own Rust `fab` binary (ADR-0014).
- **B —** stock herdr (fork only if a patch is unavoidable) plus our plugin
  (community + org features) for power users; minimal web view for departments.
- **C —** keep the full SvelteKit UI for everyone.

**Learning**
- **D —** depend on harness2 directly.
- **E —** adopt harness2's *method* (propose → probe → compose, with a persistent
  store of adopted harnesses and supported lessons) inside our own service,
  with every adopted change going through the existing `ChangeRequest` approval.
- **F —** fully automatic self-modification.

## Decision

**B + E.**

1. **Power users: herdr + our plugin.** They run herdr (stock; a fork is a
   fallback, not the plan) and open agents inside it. Our plugin adds company
   features on top of the community chat. `packages/tui` is frozen; what in it is
   still needed (workspace lifecycle, review screens) moves into the plugin or
   the backend API. This supersedes decision 2 of ADR-0014; the server-side
   workspaces of decision 1 stand.

2. **Departments: one minimal route group in the existing SvelteKit app**, role
   `assistant_user`, deliberately small (a few components, no new framework):
   - chat: messages and file upload;
   - a reasoning/step stream of the running task (read-only);
   - the finished outputs, listed and downloadable;
   - a short "my context" side panel, **scoped to the person**: connected tools,
     their place in the org (team, manager, colleagues), the policies that apply to
     their role, company mission / vision / goals. No skill, policy or agent
     editing, no company-wide lists.
   The admin pages remain for admins and are hidden for this role. Scoping is
   enforced by the backend (queries filter by the caller's personnel record),
   never only by the UI.

3. **Desktop "Assistant" folder, local only (Windows and macOS).** The person's
   own files and second brain live there. Nothing is synced to the server by the
   platform; agent output is logged server-side (ADR-0006), and what the person
   chooses to attach to a task travels with that task. Consequence: the server
   cannot see local files that were not attached, and a lost laptop is the
   person's local-disk problem (disk encryption is a deployment requirement).

4. **Learning loop (harness-learning service), approved, not automatic.**
   - *Signals:* ADR-0021 ratings and contests, work-review outcomes, explicit
     thumbs/comments, task success/failure from the audit log. All signals go
     through the existing redaction (`services/redact.py`) before use.
   - *Proposer:* for a flagged pattern, a proposer drafts a harness edit
     (prompt, guardrail, memory entry, tool guidance, skill) in the scope it
     belongs to — person, department or company.
   - *Probe:* the candidate runs against **replayed past tasks** from the eval
     log in the sandbox of ADR-0002 (default-deny egress; no live data sources),
     and a judge compares outcome with the baseline. Replay data is redacted.
   - *Compose and propose:* the result is stored as a `ChangeRequest` with
     `change_type = "harness"`, with the diff, the evidence and the measured effect.
     The existing two-stage approval applies; nothing becomes active without it.
     Policy edits and anything that widens a permission are never auto-proposed
     by the loop; they stay a human-authored path (ADR-0017).
   - *Memory:* adopted changes and the lessons that supported them are stored
     per company, versioned, and can be rolled back (the same way config is).
   - harness2 itself is used offline as a reference and for experiments in an
     isolated environment, not in the request path.

5. **Observability.** Run traces and eval results stay in the server-side
   configuration/eval log layer (owner: installation kit, ADR-0016). A viewer
   (Langfuse or Phoenix, self-hosted) is a separate decision.

## Consequences

- **Positive:** less UI to build and secure; department users get a small,
  least-disclosure surface; the learning loop reuses approval, audit and
  redaction instead of inventing new trust paths.
- **Negative / cost:** dependence on herdr's plugin API and release cadence (we
  already carry that for the community plugin); two surfaces to support (herdr and
  the minimal web view); replay-based probing needs enough clean historical tasks
  to be meaningful, and early on it will not have them.
- **Accepted residual risk:** a plausible but wrong harness edit can pass approval;
  the evidence and rollback exist to limit this. Feedback can be gamed by users;
  signals are weighted per ADR-0021's group floor and contest rules.
- **Security notes for review:**
  - the assistant-user API must reject any request for another person's data
    and any company-wide listing (object-level checks, not UI hiding);
  - reasoning streams can contain tool arguments and document content: pass them
    through redaction and the caller's scope before streaming;
  - prompt injection can reach the proposer through feedback text and task
    content; the proposer's input is treated as untrusted data and its output as a
    proposal only (ADR-0010);
  - the probe step must not have network egress or write credentials;
  - the local Assistant folder is outside platform control; the agent's file
    access to it is limited to the folder the person chooses.
- **Follow-ups:**
  1. Locate/finish the configuration + eval-log layer and define the replay
     format (it was reported done in the installer but is not in this repo).
  2. Spike: run `harness2-demo` in isolation and note what artifacts it writes.
  3. Design the `assistant_user` role and the scoped "my context" endpoint.
  4. Plugin spec: what moves from `packages/tui` into the herdr plugin.
  5. Mark ADR-0014 decision 2 as superseded once this is accepted.
