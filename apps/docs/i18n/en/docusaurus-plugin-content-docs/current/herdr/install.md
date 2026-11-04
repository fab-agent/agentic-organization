---
sidebar_position: 3
---

# Install and Deploy

> ADR-0030 · ADR-0031 · ADR-0032 · ADR-0033 (all "proposed")

The installers **download nothing**; the administrator (or MDM) supplies the files and their SHA-256 values. They run in the user's own folder; no root/SYSTEM is needed.

## User installers

| Platform | File | Note |
|---|---|---|
| Linux / macOS | `installers/user/install.sh` | `--base-url`, `--root-pub`, `--cli`, `--cli-sha256`; optional pairs: `--herdr-bin` + `--herdr-sha256`, `--release-pub` + `--release-url`; also `--dry-run`, `--uninstall` |
| Windows | `installers/user/windows/install.mjs` + `install.ps1` | Refuses an elevated session by default (`--allow-elevated` allows it) |

The installer places: the `3pa` bundle (hash-checked), the pinned root public key, optionally the Herdr binary, and a `herdr-fab` launcher that syncs the workspace and starts Herdr. Uninstall deletes only the names it wrote. The Windows path is tested in CI on Windows, Ubuntu and macOS.

**Windows limits:** the binaries and installer are not Authenticode-signed; there is no MSI and no PATH handling; the default Herdr app folder is a guess (pass `--app-home`).

## Signed release chain and `3pa self-update`

`3pa self-update` verifies a release notice signed with a separate **release key** and installs the new bundle. The release key is also offline. The tool that signs the notice is in the repository, but **the release workflow does not yet emit the unsigned `body.json`, and key rotation is manual.**

## Deployment contract (vendor-neutral)

The `installers/deploy/` folder is the single answer to *what is handed out, how it runs, is it compliant, how it updates, how it is undone*; Intune, Jamf, Ansible or a login script call the same commands.

- `deploy.conf`: `KEY=VALUE` only (public keys, URLs, hashes); no secrets, never executed.
- `deploy.sh|deploy.ps1 install` runs as the user (as root on macOS it switches to the console user; on Windows SYSTEM is refused). If already compliant it does nothing.
- `check` changes nothing; it returns 0 only if the intended bundle, entry scripts and pinned keys are exactly in place. For self-updating fleets use `check --pins-only`.
- `install` never **overwrites** a `3pa` bundle or Herdr binary whose content differs from the settings (`--force-artifacts` asks for it explicitly). The entry scripts (`bin/3pa`, the launcher) are rewritten if they were changed.
- Flags differ by shell: `deploy.sh install --config rollout/deploy.conf`, in PowerShell `deploy.ps1 install -Config rollout\deploy.conf`; `--pins-only`/`--force-artifacts` are `-PinsOnly`/`-ForceArtifacts` there.

Details: `installers/deploy/README.md` in the repository. Node.js 20+ must already be on the machine.
