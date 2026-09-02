# ADR-0012: Repo structure and release process

- **Status:** proposed
- **Date:** 2026-09-01
- **Related:** ADR-0008, ADR-0009; `.github/workflows/`

## Context and problem

New components are coming: backend `gateway` / `policy_engine` / `audit_chain`
(Python), `agent-plugin` (TS/Bun), the `3pa` workstation wrapper (Go), the
`sandbox/` image. Do these live in one repo or separate repos? How are they
versioned and released?

## Options considered

- **A — everything in this monorepo.** `backend/`, `frontend/`,
  `packages/agent-plugin/`, `packages/workstation/` (or `3pa`), `sandbox/`. A
  single PR flow, atomic changes.
- **B — the laptop agent in a separate repo.** Independent versioning/issues, but
  a cross-cutting change (gateway API + plugin + wrapper together) needs
  two-repo coordination.

## Decision (proposed)

**A — monorepo**, with path-scoped CI:

```
agentic-organization/
├── backend/            # + api/gateway.py, services/policy_engine.py, services/audit_chain.py
├── frontend/           # unchanged
├── packages/
│   ├── cli/            # existing 3pa (Docker wrapper) — to be extended (ADR-0009)
│   └── agent-plugin/   # opencode org plugin (TS/Bun)
├── sandbox/            # container image + egress-proxy config
└── docs/adr/, docs/architecture/, docs/ROADMAP.md
```

**Versioning:**

- **Server (backend+frontend):** the existing `version.py` / SemVer, container
  image tag.
- **`agent-plugin`:** its own SemVer; pinned to the opencode plugin API version;
  a compatibility matrix with the backend gateway API's `X.Y` in `docs/`.
- **`3pa` workstation:** its own SemVer; contains a **pinned opencode version**;
  `3pa --version` shows both itself and the opencode pin.

**Release CI (GitHub Actions):**

- `ci.yml` (existing) — lint/typecheck/test are preserved.
- `gateway.yml`, `policy-engine.yml`, `agent-plugin.yml`, `fabctl.yml` —
  path-filtered, run when the relevant component changes.
- `adr-guard.yml` — warns when architecture-significant paths change without an
  ADR touch.
- `e2e-nightly.yml` — the full loop (cron).
- `release-*.yml` — tag-driven: container push, `3pa` binary matrix + signing,
  plugin npm/registry publish.

## Open questions

- If `3pa` moves to Go, what happens to the existing TS `packages/cli` — a bridge,
  or removed?
- Plugin distribution: public npm, a private registry, or bundled with `3pa`?

## Consequences

- **Positive:** A cross-cutting change lands in a single PR; the version
  compatibility matrix is in one place.
- **Negative / cost:** The CI matrix grows; monorepo release orchestration needs
  care.
