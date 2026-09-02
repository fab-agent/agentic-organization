# ADR-0008: TUI strategy

- **Status:** accepted
- **Date:** 2026-09-01
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0001, ADR-0009

## Context and problem

A `career-ops`-style terminal dashboard is wanted: pipeline/log/approval panels,
an org chart, an A2A approval queue. But ADR-0001 adopted opencode as the
developer client, and opencode **already has its own TUI** (Go + Bubble Tea).

## Options considered

- **A — build our own TUI now.** opentui (Bun-only, powerful but a moving API),
  Ink (Node, mature but a ~30 FPS cap, weak mouse), or Bubble Tea (Go, single
  binary, the choice of both `career-ops` and `opencode`).
- **B — go with opencode's TUI for now**, and add our own when the need is clear.

## Decision

**B, then Bubble Tea.**

- **Now:** developers use opencode's built-in TUI. Org context (skills, A2A,
  inbox, policy status) is exposed to opencode as **MCP tools** and slash
  commands — no separate screen is needed.
- **Later (trigger: a concrete need for a non-web "operations panel"):** a
  separate **Go + Bubble Tea** binary. Rationale: a single static binary, no Bun
  requirement, the same ecosystem as `career-ops`/`opencode`, mature
  Lipgloss/Bubbles.
- **opentui** is revisited only if heavy interaction/animation/embedded imagery is
  genuinely required and Bun is already mandatory on the workstation.
- When our own TUI is written: it is a **read-only + approval** client that
  connects to the backend's existing SSE stream; it contains no agent logic
  (the ADR-0001 client/server split).

## Consequences

- **Positive:** A working TUI with zero upfront investment. Effort goes to the
  security layer and the gateway.
- **Negative / cost:** In the short term the brand/experience is opencode's. The
  `career-ops`-style rich dashboard is deferred.
- **Follow-ups:** Note the `career-ops` dashboard UX patterns (layered `View()`,
  async preview pane, column picker, smart status picker) in the notebook — a
  reference for when our own TUI arrives.
