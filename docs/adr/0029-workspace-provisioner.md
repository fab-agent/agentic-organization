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

1. **Sign in, keep nothing.** A web session token from the `3pa login` helper (password,
   `--oidc`, or `FABAGENT_WEB_TOKEN` for unattended use), held in memory only. It is not
   the persona token (ADR-0026 decision 5). Every request, including the sign-in POSTs,
   goes only to the configured platform URL and treats a redirect as an error (a redirect
   would carry the password or id_token to another host).
2. **The platform URL is parsed, not matched.** `https://` anywhere; `http://` only for the
   exact host names `localhost`, `127.0.0.1` and `[::1]`; no credentials, query or fragment. The
   library checks this before sending anything, so a look-alike such as
   `http://localhost.example` never receives the token.
3. **Pinned root.** The root public key comes from the installer / MDM (`--root-pub`,
   `FABAGENT_WORKSPACE_ROOT_PUB`, or `<state dir>/root.pub`) and is never fetched from
   the server.
4. **Revocation first.** The root-signed revocation list is fetched and ingested before the
   manifest, and the state is saved at once, so a manifest that is refused, unavailable
   (`503`) or fails the identity check cannot cost the client a revocation. The platform
   serves the list even when its own signing key has been revoked.
5. **Verify** with the TypeScript verifier (same verdicts as the Python one on a shared set
   of 60 vectors) and the strict wire parser. Nothing else is trusted before it accepts.
6. **Identity is pinned on first use** from the signed-in session's own reply
   (`identity` in `/me/workspace`) and compared on every later run; a different person
   needs an explicit `--re-enroll`. Bootstrap floors come from the same reply and are
   required only when there is no history for that person (ADR-0027). This is a stated
   trust assumption: whoever can alter the TLS-protected session reply at enrolment can
   choose the first identity and floors. A stronger model needs the installer / MDM to
   provide the identity and a checkpoint.
7. **State is checked, written atomically and never reset silently.** Every field of
   `state.json` is validated (types, safe-integer ranges, hash and id formats, one entry
   per person), because JavaScript would otherwise coerce a damaged counter into a
   comparison that passes. It is written with a full-length write loop, fsync, rename and a
   directory sync, mode 0600 in a 0700 directory (Windows has no such mode bits: there the CLI checks neither bits nor ACL - it relies on the folder being in the user's own profile or having been prepared by an installer that restricts it, as ADR-0032 does; a custom `THREEPA_WORKSPACE_DIR` on a shared location is the administrator's responsibility). The accepted state is saved **before** any
   file is touched. A corrupt file stops the run (a dangling link or odd file at `state.json` counts as
   corrupt, only a genuinely missing file is "no state yet"); `--re-enroll` keeps a copy
   of the old file and replaces it with one atomic rename of the new one, so a failed
   attempt - even a disk error while writing - leaves the old state where it was.
8. **One run at a time.** The lock file holds the pid and a random token. It is published
   whole: the content is written to a private temp file and hard-linked into place (which
   fails if a lock exists), so no reader ever sees an empty or half-written lock. There is no
   create-then-write fallback: on a file system without hard links the lock is refused
   (`locking_unsupported`) and the state directory must be on an ordinary local one. Whether the
   lock was published and whether the temp file could be tidied afterwards are separate
   facts, so a failed cleanup never strands a lock that exists; temp files of ours are swept only once older than a lock may be (an hour), so a live preparer's file is never taken. Unlock
   removes only a file with our token. A lock is *stale* when (a) its process is gone, or
   (b) it is older than an hour, which is the answer to pid reuse, or (c) it cannot be read
   as a lock and is older than ten seconds; a lock that cannot be read at all is left alone.
   A stale lock is removed only by a run holding the separate takeover mutex
   `sync.lock.takeover`, and that run judges staleness again after taking the mutex, so a
   paused process that read a stale lock earlier cannot remove the live lock of whoever took
   over in the meantime; after removing it the run creates its own lock exclusively and backs
   off if a normal acquirer was faster. The mutex is itself stale when its process is gone or
   it is older than 30 seconds. `assertOwned()` is checked before the recovery, before every
   state write and before activation, and a run that finds it lost stops.
   The hour is only safe if a sync ends long before it, so a sync stops between steps
   (each request after one minute, the whole sync after 20 minutes, checked before every
   file written (each target, not only each download) and once more before anything irreversible, with a stable `sync_timeout`; a time budget that is not a whole number of milliseconds from 1 up to those 20 minutes is refused as `bad_duration` before anything is touched; the timeout message says no new update was applied, not that nothing changed, since a rollback of an interrupted update may have run first).
   That bound is **cooperative**: a blocked disk call cannot be interrupted from JavaScript, so
   it is not a watchdog, and a machine suspended for longer, or a clock that jumps, is outside
   what this protects.
   **Limits, stated plainly:** Node has no portable kernel file lock. `assertOwned()` followed
   by a write is not one atomic step, and unlock / mutex release are read-then-remove. Two runs
   that both see the same stale takeover mutex can still race. So the serialization is very
   strong under these assumptions (no kernel-level enforcement; syncs end within minutes; one
   user's own processes), not guaranteed by the operating system. The journal (item 10) makes a
   **crashed** run recoverable; it does not make two overlapping writers safe.
9. **Download into a fresh staging directory**, checking size and SHA-256 for each file
   (the response is capped at the manifest's size; files are created with `O_EXCL`, written
   completely - short writes are continued, zero progress is an error - and measured on
   disk). One content listed with two sizes is refused before downloading.
10. **Activation is a journalled transaction.** The plan (which items go where, where each
    old item is kept, the previous managed record) is written to `.3pa-journal.json` before
    the first rename. Old items are moved to a trash folder and never deleted until the
    end; the managed record is written inside the transaction; **deleting the journal is
    the commit**. A failure rolls everything back; a crash is found on the next start and
    rolled back first. The journal is validated against the plan this program would have made:
    the trash and staging folders are real folders directly under the app home, every old item
    has its fixed place in the trash and every new one its fixed place in staging, live paths
    are unique and well formed, and `hadLive` agrees with `aside`; anything else is refused
    before a single item is moved or deleted. The app home path is made absolute once, so a
    later run from another working directory means the same folder. Half-written temp files
    next to the record and settings files are swept at the start of a run. If a rollback cannot finish, the trash and journal are
    kept and the run stops with `recovery_required`. Directory renames are not one atomic
    operation; Herdr hot-reloads mods, so a panel may reload once.
11. **Only manage what we installed.** `.3pa-managed.json` lists the layout and mods (with
    file hashes) the provisioner installed and is validated field by field before use.
    Ownership is "own property of that record", never "has that name": a mod called
    `constructor` or `toString` is an ordinary name. An existing layout or mod that is not
    in the record stops the sync before any change (`--adopt` overrides). Names Herdr ships
    are refused. A link (also a dangling one) where a folder or file is expected is refused.
12. **Links are never trusted, not even to identical bytes.** The drift scan and the
    "nothing to do" check use `lstat`: a managed file that became a link is drift and is
    repaired by the next sync.
13. **Telemetry off before first launch.** `settings.json` gets `"telemetry": false`, other
    keys kept; an unreadable settings file is reported and left alone. This is the one write
    that happens before the manifest is verified, on purpose.
14. **Unchanged content does nothing**, even though the server issues a new generation per
    request: the content digest of `{layout, mods}` is compared, and the disk is checked for
    drift first (a damaged managed file is repaired).
15. **Messages say what is true.** An unexpected file error is `fs_error` and points to
    `3pa workspace status` instead of claiming nothing changed; a failure to record the state
    after a committed update is `state_not_recorded` and says the workspace *was* updated.
16. **Errors carry codes, not server text.** A server `reason` is passed on only if it is
    `[a-z0-9_]{1,48}`; otherwise the code is `http_<status>`. Unexpected errors print a
    generic line (`THREEPA_DEBUG=1` for details). Drift is a diagnostic, not attestation
    (`3pa workspace status`, exit code 2; it also reports an interrupted update).

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

- Tests (fake platform, real signatures) cover every item above, including a child process
  that is killed in the middle of an activation at each rename and a rollback that itself
  fails; an end-to-end test starts the real backend and runs the real CLI against it.
- `/me/workspace` now also returns `identity: {company_id, person_id}`.
- The root public key must be distributed with the installer; without it the command stops
  with `root_pub_missing`.
