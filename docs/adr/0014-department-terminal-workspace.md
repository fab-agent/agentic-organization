# ADR-0014: Terminal workspace for every department

- **Status:** proposed
- **Date:** 2026-09-28
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0001, ADR-0002, ADR-0004, ADR-0005, ADR-0006, ADR-0008 (TUI technology superseded here), ADR-0015, ADR-0016

## Context and problem

The platform so far has two surfaces: the web UI for everyone, and opencode in a
laptop sandbox for developers (ADR-0001/0002). The product direction is now a
deliberate change in how the whole company works: **every department — finance,
HR, sales, legal, operations, engineering — works from a terminal workspace**
where an agent does the tool work (documents, spreadsheets, presentations, ERP
lookups) and people focus on the job itself.

The workspace must show, at a glance and without navigation:

- who I am in the organisation — company › department › role (job function),
  and the people who report to me;
- the recurring (cron) work that runs for me or my team;
- the most recent runs and their outcome;
- the agent session(s) I am working in.

[herdr](https://herdr.dev/) is the reference for the feel: a Rust + Ratatui,
Apache-2.0 terminal multiplexer that keeps agent sessions alive in a background
server, shows each agent's state (working / blocked / idle) in a sidebar, works
over SSH, and has a socket API and plugins.

ADR-0008 postponed our own TUI "until a concrete need for a non-web operations
panel". This is that need. Its technology pick (Go + Bubble Tea) predates the
herdr reference and is revisited here.

## Options considered

**Where does the agent run for non-developers?**

- **A — laptop + local sandbox (ADR-0002 for everyone).** Needs Docker on every
  finance/HR laptop, a local LibreOffice/Chrome/Docling toolchain, and per-laptop
  support. Too heavy for non-developers.
- **B — server-side workspace per person.** Each person gets a persistent,
  sandboxed workspace container on the main server (or a worker node) with the
  full toolchain pre-installed. The terminal on the laptop is a thin client that
  attaches to it (SSH or WebSocket), like herdr's remote mode. Sessions survive a
  closed lid or a dropped connection.

**TUI technology**

- **C — Go + Bubble Tea** (ADR-0008's plan).
- **D — Rust + Ratatui, own binary**, with herdr (Apache-2.0) as the reference
  and, where useful, a source of reusable pane / PTY / session-persistence code.
- **E — ship on top of herdr** as a plugin, adding only an org sidebar.

## Decision

**B + D.**

1. **Execution: server-side workspaces for departments.** Each person gets a
   long-lived workspace container (same hardening as `sandbox/`: non-root,
   default-deny egress, no host mounts) with the work toolchain baked in —
   LibreOffice headless, a PDF toolkit, headless Chromium for presentations and
   web pages, Docling. Files the agent produces are listed in the TUI and can be
   pulled to the laptop or opened in the web UI. Developers keep ADR-0002
   (laptop + sandbox) — both paths use the same gateway, policy engine and audit.

2. **Client: our own Rust + Ratatui binary** in `packages/tui` (working name
   `fab`). One static binary for macOS / Linux / Windows. It attaches to the
   person's workspace and draws the layout below. herdr is the UX and
   architecture reference; a spike (follow-up 1) decides whether we vendor parts
   of it (pane engine, PTY handling, session persistence) under its Apache-2.0
   notice or write our own. Option E is rejected because the org sidebar,
   approvals and file panes are the product, not an add-on, and a third-party
   plugin API would cap what we can build.

3. **Layout (v1):**

   ```
   ┌─ Fabrika Yazılım ───────────┬──────────────────────────────────────────┐
   │ ▸ Finance › Accounting      │                                          │
   │   Role: AP Specialist       │   agent session (opencode / chat pane)   │
   │   Reports to: A. Yılmaz     │                                          │
   │   Team: 3 people, 2 agents  │                                          │
   ├─ Recurring ─────────────────┤                                          │
   │ ● 09:00 Daily cash report   │                                          │
   │ ○ Mon  Supplier aging       │                                          │
   ├─ Recent runs ───────────────┤                                          │
   │ ✓ 09:00 Daily cash report   │                                          │
   │ ✗ 08:30 Invoice match (3)   ├──────────────────────────────────────────┤
   │ ⧗ approval: PO #4411        │ files: cash-2026-09-28.xlsx  report.pdf  │
   └─────────────────────────────┴──────────────────────────────────────────┘
   ```

   Sidebar data comes from existing APIs: org tree (`/departments`,
   `/personnel`), flows (`/flows`), runs and inbox (`/inbox`), approvals
   (`/a2a`, `/task-requests`, `/change-requests`). Keyboard-first with a visible
   key hint bar and mouse support; no command memorisation needed. TR / EN.

4. **Web UI: shrink and freeze.** The SvelteKit app gets no new features; product
   work goes to the TUI. It is cut down to what a browser does better:
   sign-in / SSO redirects, the installation wizard (ADR-0016), approvals with
   diff review (ADR-0017), file preview, and admin. Other screens (chat, agents,
   flows, …) are removed as their TUI equivalents ship. The remainder is built
   with `adapter-static` and served by FastAPI, which removes the Node server
   and the separate frontend container. Dropping it entirely was rejected for
   now: SSO needs a browser, and reviewing diffs and generated documents is
   clearer in one.

## Consequences

- **Positive:** One workspace for every department. No toolchain on laptops. The
  agent does the tool work where the tools are installed. Sessions persist.
  Everything still flows through gateway + policy engine + audit (ADR-0004/5/6).
- **Negative / cost:** Server capacity scales with head count (one container per
  active person) — needs a capacity model and idle suspension. A second client
  to maintain (Rust) next to the Node `3pa` CLI. A terminal is new for most
  non-developers — onboarding and the key hint bar matter.
- **Accepted residual risk:** Workspaces hold company documents server-side; the
  per-workspace sandbox and egress allowlist are the boundary. Documents sent to
  a cloud model or ranking API leave the premises (ADR-0015, ADR-0016 make this a
  per-install choice).
- **Follow-ups:**
  1. Spike: herdr code reuse (pane engine, PTY, persistence) vs. own; license check.
  2. Workspace container image (`sandbox/workspace/`) with the toolchain + a
     lifecycle API (create / attach / suspend / resume) on the backend.
  3. `packages/tui` skeleton: login, sidebar from existing APIs, one agent pane.
  4. Capacity model + idle suspension.
  5. Web shrink: switch to `adapter-static` served by FastAPI; remove screens as TUI equivalents ship.
