# ADR-0032: User installer for Windows

- **Status:** proposed
- **Date:** 2026-11-02
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (deliverable 3; "Windows curl/tar" in the installer matrix), ADR-0029 (provisioner), ADR-0030 (Linux/macOS installer), ADR-0031 (signed releases)

## Context

ADR-0030 covers Linux and macOS with a POSIX shell script. Windows has no `sh`; the same
contract (nothing downloaded, hashes checked on the copy, keys pinned, unsafe locations
refused, no recursive delete, fail-closed launcher) has to be kept with different file-system
rules: no mode bits, case-insensitive paths, reserved device names, drive letters and UNC paths,
alternate data streams, a `.cmd` launcher with its own quoting, and no replacing a running
program.

## Decision

1. **The logic is one Node script, `installers/user/windows/install.mjs`, with a thin
   `install.ps1`** that finds Node 20+ and passes the arguments through. Node is already
   required by `3pa`; the script also runs on Linux/macOS and is tested there, which keeps the
   reviewed behaviour (ADR-0030) and the Windows behaviour from drifting apart. `install.sh`
   stays as the dependency-free entry for POSIX.
2. **Same contract, same flags**: `--base-url --root-pub --cli --cli-sha256 [--herdr-bin
   --herdr-sha256] [--release-pub --release-url --replace-release-key] [--prefix --state-dir
   --app-home] [--replace-root] [--dry-run]`, `--uninstall [--purge-state]`. Both artifacts are
   copied to temp files and hashed before either goes live; a wrong hash installs nothing.
3. **Defaults** are per-user: prefix and state under `%LOCALAPPDATA%\3pa`, Herdr app home under
   `%APPDATA%\herdr-app` (the CLI uses the same defaults on Windows). *The Herdr app home on
   Windows is assumed; it must be confirmed against Herdr's own documentation or a real
   install before relying on the default - `--app-home` overrides it.*
4. **Refuses an elevated prompt** (integrity level check), as install.sh refuses root: the
   workspace is one person's, and an install from an administrator prompt would go into the wrong
   profile. `--allow-elevated` is the explicit override (hosted CI runners are elevated; so is a
   deliberate install into an administrator's own profile). It is a named flag, not an
   environment variable, so it cannot be set by accident.
5. **Path rules** (raw text is judged before it is normalised): absolute with a drive letter
   (no UNC, no `\\?\`); no control characters, no `..`; none of `< > " | ? * %`; no `:` after
   the drive (alternate data streams); no reserved device names (`CON`, `NUL`, `COM1`...) and no
   component ending in a dot or space. Locations are compared **case-insensitively** after links,
   junctions and 8.3 short names are resolved (`realpath.native`); never a drive root, the
   home directory or a parent of it; bin, lib, state and app home must not overlap.
6. **The state folder is private through its ACL**: the installer removes inheritance and
   grants only the current user (by SID, via `icacls`; `whoami.exe` and `icacls.exe` are run by absolute path from System32, because a first CI run showed that a `whoami` from Git for Windows can come first on PATH and answers differently). The CLI cannot check mode bits there
   (ADR-0029) and does not try.
7. **Launcher and wrapper are `.cmd` files.** Because a path can contain neither `"` nor `%`
   (decision 5), double-quoting is sufficient; the platform URL has `%` doubled. The launcher
   runs `3pa workspace sync` and starts Herdr only if it succeeds. The wrapper `3pa.cmd` (and
   the POSIX wrapper, changed in the same commit) sets `THREEPA_WORKSPACE_DIR` and
   `HERDR_APP_HOME` for this install unless the user already set them, so `3pa self-update` and
   `3pa workspace` find the pinned keys even when `--state-dir` was custom.
8. **Same ownership rules for uninstall**: only the files the installer creates are removed, by
   name; `--purge-state` removes the exact state/lock/backup/release file names and the folder
   only if it is then empty; no recursion; the app home is never touched.
9. **`3pa self-update` knows Windows** (`os: windows`, `herdr.exe`). A program that is running
   cannot be replaced on Windows: that is reported as `replace_failed` with the instruction to
   close it. Nothing is published before all downloads are verified (ADR-0031), but the two
   renames are still not one atomic step.

## What this does not do (stated plainly)

- No signing (Authenticode) of `install.ps1`, `.cmd` files or binaries; PowerShell execution
  policy may require the administrator to run it as `powershell -ExecutionPolicy Bypass -File`
  or to sign it. SmartScreen and the like are out of scope.
- No MSI/MSIX, no Start-menu entry, no PATH change (the installer prints the folder to add).
- Not tested against every Windows locale or against network drives; UNC paths are refused.
- The ACL hardening is verified only in CI on a hosted runner; the CLI itself still relies on
  the user's own profile being private.

## Verification

`installers/user/windows/install.test.mjs` runs in CI on Windows, Linux and macOS (refusals,
hash handling, pinned keys, release options, uninstall/purge grammar, Unicode paths, the real
launcher fail-closed behaviour, and on Windows the path rules and the ACL). The CLI test suite
now runs on `windows-latest` too, after fixing a real bug it found: the activation journal wrote
backslash-separated names on Windows that its own validation then rejected.

## Consequences

- One installer implementation to review for the two platforms that share Node; the shell script
  remains the zero-dependency choice on POSIX.
- The next slices are an MDM wrapper (Intune/Jamf/Ansible using these inputs), then monitoring.
