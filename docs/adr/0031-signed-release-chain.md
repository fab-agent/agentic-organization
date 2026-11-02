# ADR-0031: Signed release chain and `3pa self-update`

- **Status:** proposed
- **Date:** 2026-11-02
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (decision 7: installer, updater, core and mod-API pinned together), ADR-0027 (canonical JSON, Ed25519), ADR-0029 (provisioner), ADR-0030 (user installer)

## Context

ADR-0030's installer takes the `3pa` bundle and the Herdr binary with hashes from an
administrator and downloads nothing. After day one the machine needs a way to move to a new
version that does not depend on trusting whatever answers at a URL, and that cannot be walked
back to an older, vulnerable build.

## Decision

1. **A release is a document signed offline.** `{body, kid, sig}`; the body has exactly the
   fields `typ="3pa-release"`, `v=1`, `channel`, `version` (`MAJOR.MINOR.PATCH`, each part at most 15 digits so it is an exact integer and is compared exactly), `seq` (a
   positive integer that only increases), `issued_at`, `expires_at` (at most 90 days apart),
   and 1-16 `artifacts` `{name: "3pa"|"herdr", os: linux|macos, arch: x64|arm64, url, size,
   sha256}`. Unknown fields are refused. The signature is Ed25519 over the canonical JSON of the
   body (the ADR-0027 profile) behind the domain string `3pa-release-v1\n`, so a signature made
   for one kind of document is never accepted as another (tested against the workspace domain).
2. **A separate release key.** It is not the workspace root key (ADR-0027): releasing software
   and vouching for a person's workspace are different powers. It is generated and used offline
   (`packages/cli/scripts/release-sign.ts keygen|sign|verify`), refuses to overwrite a key, and
   refuses to emit a document the client would reject. Every output is created exclusively
   (an existing file, link or dangling link is never overwritten or followed), and both halves
   of the key pair are checked before either is created. It never goes into CI.
3. **The installer pins the key and the manifest URL** (`--release-pub`, `--release-url`,
   stored as `<state>/release.pub` and `release-url`). The key is never fetched. Replacing a
   pinned release key needs `--replace-release-key`; purge removes these files by exact name
   like the others (ADR-0030 decision 8).
4. **`3pa self-update` verifies before it downloads.** Order of authority: the pinned key's id
   must match, the signature must verify, and only then is the body read, validated and checked
   for freshness (`now < expires_at`, `issued_at` not in the future beyond five minutes). The
   manifest is limited to 64 KiB and parsed with the strict parser (duplicate keys, floats, odd
   encodings refused).
5. **Anti-rollback is by sequence and by version.** The last accepted `seq`, `version` and
   document digest per channel is kept in `<state>/release-state.json` (read through the strict parser with a 64 KiB cap, validated against a closed schema, written
   atomically in a 0700 directory; only a genuinely absent file means "no history" - a link,
   a folder, a duplicate key or any damage stops the run before any request is made). A lower `seq` or a lower version is refused
   (`release_rollback`); the same `seq` with different content is refused (`release_conflict`);
   the same document again is fine. The accepted document is recorded **before** any file is
   touched, so a later failure cannot reopen an older release.
6. **Downloads are checked against the signed size and SHA-256, and published together.** Each
   artifact is fetched with redirects refused, streamed under a cap equal to its signed size,
   written with `O_EXCL` into a temp file in the destination folder, and checked. Only when all
   needed artifacts are good are they renamed into place (Herdr first, `3pa` last). Any mismatch
   leaves the old files, removes the temp files and reports `artifact_mismatch`. Destinations
   must be absent-or-plain files. Artifact and manifest URLs must be text and https (http only for
   loopback), without credentials or fragment.
7. **One run at a time, bounded.** It takes the same lock as `workspace sync`, with a 20-minute
   cooperative budget (validated like ADR-0029's); each request is capped at 60 seconds.
8. **`--check`** reports whether an update is available without downloading or recording
   anything.

## What this does not do (stated plainly)

- It does not protect against a compromised release key, or against someone who can edit
  `release.pub` / the installed files as the same user. Key rotation is manual: a new key is
  distributed through the installer with `--replace-release-key`; a signed rotation message is
  not implemented.
- A machine that was off for longer than a document's lifetime needs a fresh document; there is
  no offline grace.
- The replacement of two files is not one atomic step: a crash between the two renames leaves
  the new Herdr with the old `3pa`; running `self-update` again completes it.
- The Herdr auto-update question (ADR-0026 decision 7) is not settled by this; this only
  covers the binary the installer put in its own folder. `3pa` does not patch a running
  process, and no Windows support yet.
- Producing the artifacts and the body is still a manual step: the release workflow builds the
  bundle, and the signature is added offline. Wiring that up (an unsigned `body.json` as a
  release asset, signed document uploaded by hand) is the next small step.

## Verification

`packages/cli/test/release.test.ts` (forged / foreign-key / other-domain / tampered / extra
field / duplicate key; expiry, clock, lifetime, urls, hashes, sizes, duplicates; rollback by
sequence and version, conflict, forward move; mismatched, short, long and over-length
downloads; folder destinations; platform without a build; time budget; strict state parsing;
a real HTTP server with a redirect refused; the signing tool end to end) and
`installers/user/e2e-update.sh` (CI, Linux and macOS: install an old bundle, publish a signed
release, the installed `3pa` replaces itself, then a release signed by another key is refused).

## Consequences

- Day-two updates need no administrator and no trust in the download host.
- The release key becomes the most valuable secret; its custody (offline, backed up) is an
  operational duty, not something the code can provide.
