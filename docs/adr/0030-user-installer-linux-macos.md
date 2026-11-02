# ADR-0030: User installer for Linux and macOS

- **Status:** proposed
- **Date:** 2026-11-02
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (decision 8, deliverable 3), ADR-0027 (trust root), ADR-0029 (provisioner)

## Context

ADR-0029 stops with `root_pub_missing` unless the installer or MDM has placed the root public
key on the machine, and says the key is never fetched from the server. Something has to put
the `3pa` CLI, that key and Herdr on a workstation, and start Herdr only after the signed
workspace has been verified. ADR-0026 lists user installers as the third deliverable.

## Decision

1. **A POSIX `sh` script, `installers/user/install.sh`, for Linux and macOS.** One file with
   no dependency besides Node.js 20+, which `3pa` needs anyway. Windows is a separate slice.
2. **It installs for one user and refuses to run as root.** Default prefix `~/.local`,
   state `~/.config/3pa/workspace`, Herdr app home `~/.config/herdr-app`. The workspace is
   per person (ADR-0027 pins one identity), so a system-wide, root-owned install would put
   one person's trust state in a shared place.
3. **It downloads nothing.** The administrator or MDM supplies the `3pa` bundle, optionally
   the Herdr binary, and a SHA-256 for each. A download step would need its own trust root
   and a release-signing story; that is a later slice (ADR-0026 decision 7), not something to
   improvise here.
4. **Hashes are checked on the copy, for every artifact before any goes live.** Each file is
   copied to a temp name in the destination directory and the copy is hashed (through stdin,
   so file-name escaping cannot alter the digest); only when all hashes match are they renamed
   into place. A mismatch on any artifact installs nothing, and temp files are removed on any
   exit or interrupt. Sources that are symbolic links are refused.
5. **The root key is validated and pinned, not trusted.** Exactly 32 bytes in canonical
   base64 (Ed25519 raw public key) or the installer stops. It is written to
   `<state>/root.pub`. If a different key is already pinned the installer refuses unless
   `--replace-root` is given, because a new root is a change of trust, not an upgrade.
6. **The platform URL follows the CLI rule on the parsed URL** (https anywhere; http only for
   localhost, 127.0.0.1, `[::1]`; no credentials, query or fragment) and is baked into the
   launcher.
   **Locations are checked on their real paths** (links resolved; bin and lib are resolved too,
   since either may itself be a link): absolute, no control characters, backslashes or `..`
   components (the file system and a path library resolve `..` in a different order relative to
   links, so such a path is refused rather than interpreted), never `/`, the home directory or a
   parent of it, and bin, lib, state and app home must not equal or contain one another. **Existing state is inspected
   before anything is changed**: a state folder that is a link, someone else's, or unreadable,
   or a `root.pub` that is not a regular file, stops the install ("cannot look" is never "not
   there"), and the pinned-key comparison happens before any write.
7. **The `herdr-fab` launcher fails closed.** It runs `3pa workspace sync` and starts Herdr
   only if that succeeds; otherwise it prints a message and exits non-zero. Values written
   into the generated script are single-quote escaped (tested with a path containing a quote
   and a space). Without a Herdr binary only the CLI and the key are installed.
8. **Uninstall removes only what the installer creates, by name.** The wrappers, `3pa.mjs` and
   `herdr` in its lib folder; the folder goes only if it ends up empty. `--purge-state` removes
   the pinned key and the sync state/lock/backup files (`root.pub`, `state.json*`,
   `sync.lock*`) and then the folder only if it is empty, so a state folder that already held
   other files (even one the installer was pointed at) keeps them; there is no recursive
   delete and no marker file to forge. `--dry-run` with `--uninstall` is refused rather than
   ignored. Sync history is kept without `--purge-state`, because deleting it would let an old
   workspace be replayed (ADR-0029). The Herdr app home is never touched.

## What this does not do (stated plainly)

- The URL is judged after WHATWG normalisation, like the CLI (tab or newline characters inside
  it are dropped by the parser, not rejected).
- Needs Node.js 20+, `sha256sum` or `shasum`, and the usual `sh` tools (`sed`, `tr`, `cp`, `mv`).
- Not transactional across a crash: a kill between two renames can leave the CLI installed
  without the launcher; running the installer again completes it.

- It does not make the installed files tamper-proof: the same user can edit anything in
  their own home. Nothing here is attestation (ADR-0026 decision 4).
- Trust starts with whoever hands over the files and hashes; the hashes protect against
  corruption and substitution in transit, not against a malicious administrator.
- No signing or notarisation of the bundle, no auto-update, no Windows, no MDM profile
  yet; the Herdr auto-update question (ADR-0026 decision 7) is still open.
- Installing Herdr without sandboxing mods is Herdr's property (unsandboxed JS), unchanged.

## Verification

`installers/user/test.sh` (80 checks, run in CI on Linux and macOS): every refusal above,
a hash mismatch leaving nothing behind, a full install, launcher flow and fail-closed
behaviour, quote-in-path, root replacement, idempotence, uninstall and `--purge-state`.
A CI step also installs the real bundle and runs `3pa workspace status`.

## Consequences

- MDM can wrap this script: it needs the three inputs and the per-user run context.
- The next slices are the download/update chain with a release signature, then Windows.
