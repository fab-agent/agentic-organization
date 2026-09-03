# Version compatibility matrix

The workstation-agent layer ships several independently-versioned pieces
(ADR-0012). They are released together from one tag but consumed separately, so
this table is the source of truth for what works with what.

| Piece | Version source | Notes |
|-------|----------------|-------|
| **Backend gateway API** | `backend/version.py` (server SemVer) | The `/v1/*`, `/policy/decide`, `/workstation/*`, `/.well-known/opencode` contract. Breaking changes bump **major**. |
| **`agent-plugin`** | `packages/agent-plugin/package.json` | Talks to the backend gateway API. Pinned to an opencode plugin-API range via `peerDependencies["@opencode-ai/plugin"]`. |
| **`3pa` CLI** | `packages/cli/package.json` | Talks to the backend `/workstation/*` + `/.well-known`. Carries the **pinned opencode version**. |
| **opencode** | `sandbox/Dockerfile` `ARG OPENCODE_VERSION` | Currently **`1.18.26`**. Bumping it requires re-running the ADR-0011 managed-config bypass review (`OPENCODE_PERMISSION`, object-merge). |
| **sandbox image** | release tag | Bundles opencode + `agent-plugin` + the baked managed config. |
| **egress image** | release tag | tinyproxy allowlist proxy (ADR-0010 layer 3). tinyproxy `1.11.x` — `FilterExtended` (renamed `FilterType` in a later release). |

## Support policy

- **Backend ↔ plugin/CLI:** the backend keeps the previous **minor** of the
  gateway API working. `3pa doctor` / the plugin warn on a major mismatch.
- **`3pa` ↔ opencode:** `3pa` only launches the opencode version it pins; the
  sandbox image is built with that same pin, so a `3pa run` against a freshly
  built image always matches.
- **Signing key:** `/.well-known/opencode/pubkey` serves `previous_key_id` during
  a rotation window so a `3pa` pinned to the old key rolls over automatically
  (ADR-0011).

## Current release

| | |
|--|--|
| backend gateway API | `0.x` (pre-1.0 — minors may break) |
| `agent-plugin` | `0.1.0` |
| `3pa` CLI | `0.1.0` |
| opencode pin | `1.18.26` |
