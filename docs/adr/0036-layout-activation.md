# ADR-0036: Showing the person their layout (layout activation)

- **Status:** proposed
- **Date:** 2026-11-02
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (decision 4), ADR-0029 (provisioner), ADR-0030/0032 (installers)

## Context

The provisioner installs `layouts/<id>.json` and the mods it needs, but Herdr keeps showing the layout
the person last had (`main` on a fresh home). Without a switch the person has to find and pick the
role layout themselves. Facts about Herdr, read from the pinned source of `herdr-app`:

- `herdr-app do layout.switch --name <layout>` shows `layouts/<name>.json` in the **open** window, over a
  control socket in the app home (`$HERDR_APP_HOME/herdr-app.sock`); with no window it fails
  (`no Herdr window at ...`, exit 1). It dispatches on `argv[1]`, not on the program's file name, so the
  copy the installer places as `herdr` answers the same way.
- `herdr-app status` reports, among other things, the layout the window shows.
- Herdr reloads a changed `layouts/<name>.json` live ("within a second"). Which layout is shown is kept
  in Herdr's own bookkeeping (`shared.json`, "written by Herdr"), not in a documented setting.

## Decision

1. **Use the app's own command; write none of Herdr's files.** Activation runs `<herdr> status` and
   `<herdr> do layout.switch --name <id>` with `HERDR_APP_HOME` set, as an argument vector (no shell),
   with timeouts. It never edits `shared.json`, never signals or restarts Herdr.
2. **Once per change, not on every sync.** `sync` reports `layoutChanged` when the installed layout id
   differs from the one the machine had (a first install counts). Only then a small **pending record**
   (`activation.json` in the private state folder: unique request id, layout name, time) is written. A change of the layout
   file's *content* is not a layout change: Herdr reloads those live. A person who later switches to
   another layout on purpose is not fought: the record is removed once it has been honoured, and an
   unanswered one expires after 7 days.
3. **One worker serves a request; a newer request is never lost.** A worker **claims** the record by one
   atomic rename (`activation.json` -> `activation.claimed.<random>`): of several workers (a launcher
   started three times, a sync and a launcher) exactly one gets it and the others stop at once, so the
   same request is never switched twice and waiting workers do not pile up. A request written afterwards
   is a different file that no other worker can remove. A claim that is given back (no window, refused
   switch) is restored with a hard link, which fails if a newer request already exists - the newer one
   wins. Just before the switch the worker looks again: if a newer request is waiting it is
   `superseded` and the older layout is not switched to. A claim whose worker died is restored by the next
   worker once it is 5 minutes old. The record and its folder are trusted only if the folder is the caller's
   own private one (not a link, not shared; on Windows the state folder's ACL is the installer's job,
   ADR-0032); the file is read without following a link and at most 4 KiB.
4. **Honoured only when it can be verified.** With a window open the switch is done and `status` is read
   again; only if the window now shows the layout is the record cleared. A refusal, or a window that says
   yes but does not show it, keeps the record (`failed`). No window means the record stays (`no_window`).
5. **Where it runs.**
   - `3pa workspace sync` tries once straight after a successful sync when the Herdr binary is known
     (`THREEPA_HERDR_BIN`, which the wrapper the installer wrote sets; or `--herdr-bin`); `--no-activate`
     turns it off. A failure is one dim line and never changes the sync's result.
   - `3pa workspace activate [--wait N] [--quiet]` does it on demand. N is a real deadline (status
     calls count against it, each with the remaining time as its timeout), at most 120 s, for the window
     to appear; after that the switch and its check take at most 45 s more. A record that expires while
     waiting is not served.
   - The `herdr-fab` launcher starts `3pa workspace activate --wait 60 --quiet` **in the background**
     before it starts Herdr (POSIX `( ... & )`, Windows `start "" /b`), silent, so the first start after
     an update lands on the right layout without the launcher waiting for it.
6. **Inputs are narrow.** The layout name comes from the signed manifest and is re-validated against the
   layout name grammar (`[a-z0-9][a-z0-9._-]{0,63}`) before it is stored and again when read; a damaged,
   oversized, foreign, expired or future-dated (beyond 5 minutes of clock skew) record means "nothing to do", never a switch to an arbitrary name.
   The Herdr binary path comes from the installer's wrapper or the flag, never from the manifest; it must
   be an absolute path to a real file (not a link).

## What this does not do (stated plainly)

- If no window is ever open while the record is valid, nothing is switched; it expires.
- It does not choose between layouts, force the layout, or change it again after the first honoured switch.
- It relies on `herdr-app status` printing JSON with a `layout` string and on the `do layout.switch --name`
  form of the documented command; a Herdr that changes these makes activation report `failed` and leaves
  everything else untouched. Verified against the Herdr source, not against a running window here.
- The Windows background start (`start "" /b cmd ...`) is exercised only structurally in tests.

## Verification

CLI: strict pending record (absent, damaged, foreign keys, bad name, oversized, expired, future); a
request for a bad name is refused; a folder that is shared or a link is not trusted; three concurrent
workers send exactly one switch; a newer request written while another is served is never removed (same
name and different name); a request arriving after the window is found supersedes; a dead worker's claim
comes back and never overwrites a newer request; a slow `status` cannot stretch the wait (virtual clock); an
expiring record is not served; the exact argument vectors and app
home; switched / already / no window (with polling and the wait cap) / refused / not shown afterwards;
the binary must be absolute, existing, not a link; a real process runner with a stand-in app script.
Provisioner: `layoutChanged` for first install, content-only change, new id, no-op. End to end with the
real server and CLI: a changed layout is shown once through a stand-in app; a second sync leaves a
person who moved elsewhere alone; without a window the record waits and `activate` later does it; a
wrong binary path never fails the sync. Installers: the wrapper names the installed Herdr only when there
is one; the launcher starts the switch silently in the background after the sync and before Herdr.
