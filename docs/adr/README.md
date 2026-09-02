# Architecture Decision Records

This directory holds the project's architecture decisions (ADRs). Each ADR records
a single decision, its context, and its consequences. Decisions can change; old
ADRs are not deleted — they are **superseded** by a newer ADR.

Format: a [MADR](https://adr.github.io/madr/) derivative — see [`0000-template.md`](0000-template.md).

## Status labels

- `proposed` — under discussion, not yet binding
- `accepted` — decided, being implemented
- `superseded by ADR-XXXX` — replaced by a newer decision
- `deprecated` — no longer valid, with no replacement decision in its place

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-adopt-opencode-as-workstation-client.md) | Adopt opencode as the developer workstation client | accepted |
| [0002](0002-execution-model-laptop-plus-sandbox.md) | Execution model: laptop + mandatory local sandbox | accepted |
| [0003](0003-threat-model-and-enforcement-boundaries.md) | Threat model and enforcement boundaries | proposed |
| [0004](0004-central-llm-gateway.md) | Central LLM Gateway (OpenAI-compatible proxy, BYO upstream) | accepted |
| [0005](0005-executable-policy-engine.md) | Executable Policy Engine (fail-closed broker) | proposed |
| [0006](0006-tamper-evident-audit.md) | Tamper-evident audit (hash-chained, one-way stream) | proposed |
| [0007](0007-agent-identity-and-credentials.md) | Agent identity and short-lived credentials | accepted |
| [0008](0008-tui-strategy.md) | TUI strategy (opencode's TUI for now, Bubble Tea later) | accepted |
| [0009](0009-workstation-wrapper-cli.md) | Workstation wrapper CLI (`3pa`) responsibilities and distribution | accepted |
| [0010](0010-injection-defense-strategy.md) | Injection defense strategy (provenance, egress allowlist) | accepted |
| [0011](0011-managed-config-and-precedence.md) | Managed config and config precedence | proposed |
| [0012](0012-repo-structure-and-release.md) | Repo structure and release process | proposed |
| [0013](0013-llm-audit-severity-scoring.md) | LLM audit severity scoring | proposed |

## Adding a new ADR

1. Copy `0000-template.md`, give it the next number.
2. Fill it in, start it at `proposed` status.
3. Add its row to the table above.
4. Open a PR. The `adr-guard` workflow warns when architecture-significant files
   change without an ADR.
