# ADR-0012: Repo structure and release process

- **Status:** accepted (monorepo + path-scoped CI + `release.yml` done; backend/frontend image push + Go `3pa` pending)
- **Date:** 2026-09-01 (accepted 2026-09-03)
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

## Implementation status (2026-09-03)

- Monorepo (option A). Path-scoped CI: `ci.yml`, `gateway.yml`,
  `policy-engine.yml`, `agent-plugin.yml`, `cli.yml`, `sandbox.yml`,
  `postgres.yml`, `adr-guard.yml`.
- **`release.yml`** — tag-driven (`v*`) or manual `dry_run`:
  - `sandbox` + `egress` container images → GHCR
    (`ghcr.io/<owner>/agentic-org-{sandbox,egress}:<version>` + `latest`).
  - `3pa` CLI → a single self-contained ESM bundle
    (`scripts/bundle.mjs` → `dist/3pa.mjs` + `.sha256`), attached to the GitHub
    Release.
  - `agent-plugin` + `cli` npm packages → GitHub Packages
    (`https://npm.pkg.github.com`, `publishConfig` in each `package.json`).
- **opencode pinned** to `1.18.26` (`sandbox/Dockerfile` `ARG OPENCODE_VERSION`).
- Compatibility matrix: `docs/architecture/version-compat.md`.
- Not yet: backend/frontend image push (still compose build-local); a Go `3pa`
  binary matrix + code signing / notarization; an `e2e-nightly.yml`.

## Open questions

- If `3pa` moves to Go, what happens to the existing TS `packages/cli` — a bridge,
  or removed?  (Current call: keep TS; the ESM bundle is the "one file" story.)

## Consequences

- **Positive:** A cross-cutting change lands in a single PR; the version
  compatibility matrix is in one place.
- **Negative / cost:** The CI matrix grows; monorepo release orchestration needs
  care.
