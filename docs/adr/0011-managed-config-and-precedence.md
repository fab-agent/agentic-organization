# ADR-0011: Managed config and config precedence

- **Status:** proposed
- **Date:** 2026-09-01
- **Related:** ADR-0001, ADR-0003, ADR-0009

## Context and problem

How is org policy (the gateway URL, allowed providers, `permission` rules,
`/share` disabled, default MCP servers) imposed on opencode, and **how much** can
the user override it?

opencode config precedence (low → high): remote (`.well-known/opencode`) <
global < `OPENCODE_CONFIG` < project < `.opencode/` < `OPENCODE_CONFIG_CONTENT` <
**managed config** (`/etc/opencode/…`, root-owned) < macOS managed preferences.

**Known weakness:** even the managed config can currently be bypassed via the
`OPENCODE_PERMISSION` env var and object-merge behaviour (opencode #22292,
#6358).

## Decision (proposed)

- **Managed config INSIDE the container.** `3pa` (ADR-0009) runs opencode inside
  the sandbox and writes `/etc/opencode/managed-settings.json` **at container
  image build time** — the user being root on the host does not change this.
- **`.well-known/opencode`** is served from the backend (`api/well_known.py`);
  dynamic org policy (gateway URL, MCP servers, model allowlist) is updated
  without re-provisioning the laptop.
- **Signing:** `3pa` verifies the signature of the config + policy bundle it
  fetches (the backend signs with a private key). If it does not verify, it does
  not run.
- **Against the known bypasses:** in the container environment, `OPENCODE_PERMISSION`
  and similar env vars are cleaned/fixed by `3pa`; the plugin asserts at startup
  that critical settings have the expected value at runtime, and if not, audits +
  stops the session. This is still **soft** (ADR-0003).
- The opencode version is **pinned** by `3pa`; an upgrade is tested and shipped in
  a new release (ADR-0012).

## Open questions

- On macOS, how are managed preferences guaranteed inside the VM/container?
- Config bundle signing key rotation.
- How much freedom is left to project-level `opencode.json` (in the repo) — a
  whitelisted set of fields that cannot override org settings?

## Consequences

- **Positive:** Policy distribution does not require a laptop re-image; the
  in-container managed config closes the host-root bypass.
- **Negative / cost:** The bypass surface must be reviewed again on every opencode
  upgrade. Signing infrastructure.
