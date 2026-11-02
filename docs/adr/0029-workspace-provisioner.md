# ADR-0029: Workspace provisioner (`3pa workspace sync`)

- **Status:** proposed
- **Date:** 2026-11-02
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (decisions 3, 4), ADR-0027 (manifest), ADR-0028 (`/me/workspace`)

## Context

Herdr mods are unsandboxed code and Herdr signs neither layouts nor mods
(`herdr-app/docs/security.md`). What reaches the user's app home is therefore decided
entirely by the client that writes it. The provisioner is that client: it must never
install anything the root key did not vouch for, never lose rollback protection, and
never leave a half-installed workspace.

## Decision

`3pa workspace sync` (library: `packages/cli/src/utils/provisioner.ts`):

1. **Sign in, keep nothing.** A web session token from the existing `3pa login` helper
   (password, `--oidc`, or `FABAGENT_WEB_TOKEN` for unattended use), held in memory only.
   It is not the persona token (ADR-0026 decision 5). Requests send it only to the
   configured platform URL and treat a redirect as an error.
2. **Pinned root.** The root public key comes from the installer / MDM (`--root-pub`,
   `FABAGENT_WORKSPACE_ROOT_PUB`, or `<state dir>/root.pub`) and is never fetched from
   the server.
3. **Verify first** with the TypeScript verifier (`workspace-manifest.ts`, same verdicts as
   the Python one on a shared set of vectors) and the strict wire parser. Nothing else is
   trusted before it accepts.
4. **Identity is pinned on first use** from the signed-in session's own reply
   (`identity` in `/me/workspace`) and compared on every later run; a different person
   needs an explicit `--re-enroll`. Bootstrap floors come from the same session reply and
   are required only when there is no history for that person (ADR-0027).
5. **Save the accepted state before touching any file**, atomically (temp file, fsync,
   rename) with mode 0600 in a 0700 directory, under an exclusive lock (a lock left by a
   dead process is taken over). A manifest that is refused after a revocation list was
   taken still saves that list. A corrupt state file is never reset silently; `--re-enroll`
   moves it aside and starts over from the server's floors.
6. **Download into a fresh staging directory**, checking size and SHA-256 for each file
   (the response is size-capped to the manifest's size, files are created with `O_EXCL`
   so a path collision aborts). Nothing live changes until every file has passed.
7. **Activate as a transaction.** Replaced items are moved into a trash directory, staged
   ones renamed in, and any failure restores the old items; the trash and staging are
   removed at the end. A failed sync leaves the previous workspace exactly as it was.
   Directory renames are not a single atomic operation; Herdr hot-reloads mods, so a
   panel may reload once.
8. **Only manage what we installed.** `.3pa-managed.json` in the app home lists the layout
   and mods (with file hashes) the provisioner installed. A layout or mod that exists and
   is not in that record stops the sync before any change (`--adopt` overrides). Names
   Herdr ships (`main`, `terminals`, `win98`; the built-in mods) are refused, because Herdr
   rewrites them whole on every start. A link in the app home, or where a real folder is
   expected, is refused and never followed.
9. **Telemetry off before first launch.** `settings.json` gets `"telemetry": false`, other
   keys kept; an unreadable settings file is reported and left alone.
10. **Unchanged content does nothing**, even though the server issues a new generation per
    request: the content digest of `{layout, mods}` is compared, and the disk is checked
    for drift first (a damaged managed file is repaired).
11. **Drift is a diagnostic, not attestation** (`3pa workspace status`, exit code 2):
    missing, modified or extra files in managed mods, and mods that are neither managed nor
    shipped by Herdr. The same user can edit the record too (ADR-0026 decision 4).

## What this does not do

- It does not choose which installed layout Herdr shows; that is a runtime action in the
  app (`layout.switch`), left to the launcher.
- It does not stop a user from adding their own mods or running another Herdr instance, and
  it does not protect against the same OS user editing the app home or the state file.
- Windows semantics (renames over open files, reparse points) are not tested; the code uses
  portable calls and refuses links, but only Linux/macOS are exercised.
- Reporting drift to the server (an audit signal), the Herdr launcher integration, and the
  installers (ADR-0026 deliverable 3) are the next slices.

## Consequences

- A test suite with a fake platform covers install, no-op, change, removal, tampered / short
  / oversized downloads, activation failure with restore, unmanaged and shipped names,
  links, settings, replay, identity, revocation, corrupt state, lock and drift; and an end
  to end test starts the real backend and runs the real CLI against it.
- `/me/workspace` now also returns `identity: {company_id, person_id}`.
- The root public key must be distributed with the installer; without it the command stops
  with `root_pub_missing`.
