# ADR-0011: Managed config and config precedence

- **Status:** accepted (serve + verify + in-container injection + key rotation done; env-bypass hardening pending)
- **Date:** 2026-09-01 (accepted 2026-09-03)
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

## Decision

- **Managed config INSIDE the container.** `3pa` (ADR-0009) runs opencode inside
  the sandbox with the managed config at `/etc/opencode/opencode.json`
  (opencode's Linux managed-config path). The image bakes a fallback copy; on
  every `3pa run` the verified `/.well-known/opencode` bundle is bind-mounted
  over it. The user being root on the host does not change this.
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

## Implementation status (2026-09-03)

- `GET /.well-known/opencode` (`api/well_known.py`) serves the org's opencode
  config — a **complete drop-in**: `plugin`, `instructions`
  (`/etc/opencode/base-prompt.md`, ADR-0010), `provider` → gateway, `mcp`,
  `share: disabled`, `permission` defaults, and an `x-fabagent` block (base URL,
  disabled providers, policy mode / `fail_closed`). Assembled from `AppConfig`.
- **Ed25519-signed** (`services/wellknown_sign.py`): key at
  `data/.wellknown_ed25519` (0600). `signature` over the canonical JSON,
  `key_id`, `algorithm`.
- **Key rotation:** `wellknown_sign.rotate_key()` archives the current key to
  `.wellknown_ed25519.prev` and generates a new one; `GET /pubkey` also returns
  `previous_key_id` during the grace window. `3pa` auto-accepts + re-pins a
  rotation it can see advertised (pinned == `previous_key_id`); an unexplained
  key change still needs `--accept-key-change`. `drop_previous_key()` ends the
  window.
- **In-container injection:** `3pa run` fetches + verifies the bundle, writes
  the config to a temp file, and bind-mounts it over
  `/etc/opencode/opencode.json` in the sandbox (compose `-v`, or
  `FABAGENT_MANAGED_CONFIG` for `sandbox/run.sh`). The image's baked copy is now
  the offline / `--no-verify` fallback only.
- Not yet: `OPENCODE_PERMISSION` / env-var bypass hardening; a runtime assert in
  the plugin that critical settings match; an operator UI / CLI for `rotate_key`.

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
