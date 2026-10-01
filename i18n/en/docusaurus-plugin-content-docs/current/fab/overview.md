---
sidebar_position: 1
---

# Department Workspace (fab): Overview

**fab** is the client in which every department (finance, accounting, sales…) works from the terminal. It is a single binary written in Rust + Ratatui. A person signs in, connects to **their own workspace** running on the server, and works there with **a single agent**. The agent produces documents, spreadsheets and presentations; it reaches the company's tools under policy and audit.

> The [Developer Workstation](/workstation/overview) (opencode + laptop sandbox) stays as it is. `fab` is the second path that uses the same gateway, policy engine and audit chain. That is why the web interface does not change.

## What exists and what does not

| Part | Status |
|---|---|
| `fab` client: sign-in, sidebar, local agent pane, `fab workspace`, `fab sync` | Works, tested |
| Workspace API (create, resume, suspend, files, attach ticket) | Works, tested |
| One agent per person, token-budgeted prompt assembly, intent classification | Works, tested |
| **My work review** (`v`), ratings and contesting, training signal | Works, **off** per company by default |
| Calibration tool, rubric linter, sampled rating | Works; **not measured** with live Jev |
| Workspace image (LibreOffice, PDF tools, headless Chromium) | First version; **not run** in Docker |
| **A real workspace runtime** | **None**: only a `FakeRuntime` for tests |

So today `fab` is not ready for use at a real customer: there is no real workspace runtime on the server side, and fit rating has not been measured with the live Jev API and has not passed legal review. For details see the [Administrator Guide](/fab/enablement).

## The screen

```
┌─ Company ───────────────────┬──────────────────────────────────────────┐
│ ▸ Finance › Accounting      │                                          │
│   Role: AP Specialist       │   agent session                          │
│   Reports to: A. Yılmaz     │                                          │
├─ Recurring ─────────────────┤                                          │
│ ● 09:00 Daily cash report   │                                          │
├─ Recent runs ───────────────┤                                          │
│ ✓ 09:00 Daily cash report   ├──────────────────────────────────────────┤
│ ⧗ approval: PO #4411        │ files: cash-2026-09-28.xlsx              │
└─────────────────────────────┴──────────────────────────────────────────┘
```

The sidebar is fed by existing APIs (org tree, flows, inbox, approvals). It is keyboard-first; key hints are shown on the bottom line.

## Sections

- [Workspace and sync](/fab/workspace): lifecycle, attaching, the local folder
- [The person's agent and prompt](/fab/agent-and-context): one agent, "My area", token budget, intent classification
- [Work review](/fab/work-review): what is collected, what is never collected, who sees what
- [Fit rubric](/fab/fit-rubric): rating, calibration, shadow period, training signal
- [Administrator guide](/fab/enablement): switches, prerequisites, verification, known limits

All the architecture decisions are in the `agentic-organization` repository under `docs/adr/` (ADR-0014, 0018–0021). These ADRs are still in `proposed` status.
