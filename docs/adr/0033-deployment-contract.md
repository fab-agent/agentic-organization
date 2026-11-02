# ADR-0033: Deployment contract (vendor-neutral MDM runbook)

- **Status:** proposed
- **Date:** 2026-11-02
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (deliverable 3, MDM), ADR-0030/0032 (installers), ADR-0031 (releases)

## Context

The installers take their inputs as flags. A fleet needs the same thing from a management system:
a place for the public keys, URLs and hashes; a way to run as the logged-in user; a detection rule;
an idempotent install. Vendor templates (Intune, Jamf, Ansible roles) cannot be verified here
without a tenant, and the product in use is not fixed.

## Decision

1. **A settings file, parsed as data.** `deploy.conf` is `KEY=VALUE` lines (`BASE_URL`, `ROOT_PUB`,
   `RELEASE_PUB`, `RELEASE_URL`, `CLI_FILE`, `CLI_SHA256`, `HERDR_FILE`, `HERDR_SHA256`). Unknown or
   repeated keys, quotes, `$`, backslash and control characters are refused; nothing is sourced or
   evaluated; hashes are 64 lowercase hex; pairs (`HERDR_*`, `RELEASE_*`) go together. It holds only
   public keys, URLs, file names and hashes.
2. **One implementation, `deploy.mjs`** (`install` and `check`), driven by two thin launchers:
   `deploy.sh` (macOS/Linux) and `deploy.ps1` (Windows). `install` calls the Node installer
   (ADR-0032) with the settings; it never reimplements its rules and therefore inherits its refusals
   (hashes, unsafe locations, replacing a pinned key only with an explicit flag - `deploy.mjs` has
   no way to pass that flag).
3. **Runs as the person, not as root/SYSTEM.** `deploy.sh` as root switches to the macOS console user
   or to `--user NAME` (`runuser`, else `sudo -n -u`) with a clean environment and the user's own
   home, after validating the name (`[A-Za-z0-9._-]`, existing, not `root`); as an ordinary user it
   refuses to act for anyone else. `deploy.ps1` refuses SYSTEM.
4. **`check` is the detection rule**: read-only; exit 0 only if the installed bundle's SHA-256 and the
   pinned root key, release key and release URL equal the settings. **`install` is idempotent**: if
   `check` passes it does nothing.
5. **Updates are not deployments**: new versions arrive through signed releases (ADR-0031). A user
   who updated has a newer bundle than `deploy.conf` names; the runbook says how to treat that.
6. **Vendor-specific packaging is out of scope** until a product is chosen; the runbook states the
   run context each family needs.

## What this does not do

- No Intune `.intunewin`, Jamf pkg/policy, or Ansible role; no tenant testing.
- No signing-key recovery (still to be written) and no automatic key rotation.
- `check` does not verify the Herdr binary or the workspace content; drift reporting is a later slice.

## Verification

`installers/deploy/deploy.test.mjs` (CI on Linux, macOS, Windows): settings parsing negatives
(unknown key, injection characters, duplicates, bad hash, unpaired settings), `check` writes nothing,
install/idempotence/drift detection (each pinned value), wrong hash and missing bundle refusals, a
pinned-key swap refused, `deploy.sh` user rules (cannot act for another user, root needs a named
safe user, not `root`, unusual names refused).
