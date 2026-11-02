# Deploying 3pa + Herdr to a fleet (vendor-neutral runbook)

This folder is the **deployment contract** (ADR-0033): what you hand out, how it runs on a user's
machine, how you know it worked, how it updates, how you undo it. It does not depend on one MDM
product. Anything that can copy a folder and run a command **as the logged-in user** can use it:
Intune, Jamf, Kandji, Workspace ONE, Ansible, a login script, or a person with a USB stick.

## What you hand out (one folder per release of the *installer*, not per update)

```
rollout/
  deploy.conf        # copy of deploy.conf.example, filled in (public keys, URLs, hashes only)
  root.pub           # the workspace root PUBLIC key (ADR-0027)
  release.pub        # the release PUBLIC key (ADR-0031)         [optional but recommended]
  3pa.mjs            # the first 3pa bundle           (npm run bundle in packages/cli)
  herdr / herdr.exe  # the Herdr binary of the pinned app+core pair                     [optional]
installers/          # this repository's installers/ folder, unchanged
```

Never put a private key, a password or a token in this folder. The root key stays offline; the
release key stays offline (ADR-0031). `deploy.conf` is parsed as `KEY=VALUE` lines only - nothing
in it is executed.

## Run it (as the user, never as root / SYSTEM)

| Platform | Command | Run context |
| --- | --- | --- |
| macOS (MDM, as root) | `sh installers/deploy/deploy.sh install --config rollout/deploy.conf` | switches to the **console user** by itself |
| Linux (Ansible, as root) | `sh installers/deploy/deploy.sh install --config rollout/deploy.conf --user alice` | switches to `alice` (`runuser`/`sudo`) |
| macOS / Linux (login script) | the same, as the user | acts for that user only |
| Windows (Intune etc.) | `powershell -ExecutionPolicy Bypass -File installers\deploy\deploy.ps1 install -Config rollout\deploy.conf` | **the logged-on user's** credentials; SYSTEM is refused |

Needs Node.js 20+ on the machine (deploy it first; `3pa` needs it anyway).

## Detect (the MDM "is it compliant?" rule)

`deploy.sh check --config ...` / `deploy.ps1 check -Config ...` change nothing and exit **0 only if**
this user has the intended bundle (and Herdr, when configured) by SHA-256, the two entry scripts
exactly as the installer writes them, and the intended pinned root key, release key and release
URL; otherwise 1, with the reasons on stdout (2 = the settings themselves are invalid).
`install` is idempotent: when the check would pass, it does nothing.

**Self-updating fleets:** after `3pa self-update` the bundle differs from `deploy.conf` (which names
the *first* bundle), so the full `check` reports it. Either use `check --pins-only` (PowerShell
`-PinsOnly`) as the detection rule, or update `deploy.conf` to the new bundle's hash. `install` never
overwrites a file that differs from the settings - it keeps it, says so, and adds only what is
missing; `--force-artifacts` (`-ForceArtifacts`) is the explicit way to put the settings' files back.
A file that is *missing* is installed from the settings (the bootstrap version): run
`3pa self-update` afterwards.

The helper supports the platform default install location only (`~/.local`, `%LOCALAPPDATA%\3pa`) and
honours `THREEPA_WORKSPACE_DIR` for the state folder in both `install` and `check`.

## Updates, rollback, rotation

- **New version:** publish a signed release document (`packages/cli/scripts/release-sign.ts`) at
  `RELEASE_URL`; users run `3pa self-update` (or schedule it). No re-deployment.
- **Rollback:** refused on purpose (sequence and version only increase). Ship a *newer* release that
  contains the older, fixed build.
- **Root or release key rotation:** a new key is a change of trust. Re-run the installer with
  `--replace-root` / `--replace-release-key` (add them to a one-off script; `deploy.mjs` never does).
  Plan rotation before you need it (the signing-key recovery runbook is still to be written).
- **Uninstall:** `node installers/user/windows/install.mjs --uninstall [--purge-state]` as the user.
  The Herdr app home is never touched.

## Things that will bite you

- Windows hosted/RMM runners are often **elevated**: the installer refuses unless you pass
  `-AllowElevated` and accept that it installs into that account's profile.
- Path rules are strict (no `%`, quotes, `..`, UNC on Windows). Keep the defaults unless you must.
- Paths in `deploy.conf` are relative to the file; the helper does not follow links for the bundle.
- Antivirus/SmartScreen/Gatekeeper: nothing here is Authenticode-signed or notarised yet (ADR-0032).
