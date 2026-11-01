# ADR-0027: Signed workspace manifest (trust root, rotation, replay protection)

- **Status:** proposed
- **Date:** 2026-11-01
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0011, ADR-0026 (decision 3), `docs/architecture/herdr-plugin-spec.md`

## Context and problem

ADR-0026 has the client-side provisioner (`3pa`) write a role's Herdr layout and mods
into the user's app home. Herdr runs mods as unsandboxed code and does not sign
layouts or mods, so the only thing between a user's machine and arbitrary code is the
check the provisioner makes. The older `wellknown` signing flow cannot be reused as the
trust protocol (Codex review of ADR-0026, findings 2 and 3):

- on key rotation the client re-pins whatever new key arrives with a matching
  `previous_key_id`, which an attacker who can alter responses can supply with their
  own key, signature and the known old fingerprint;
- the first contact is trust-on-first-use;
- the signature covers the content but not freshness, so an old valid manifest can be
  replayed;
- it keeps the previous *private* key on disk with no expiry.

## Decision

Three layers, all Ed25519 (`cryptography` is already a dependency), implemented in
`backend/services/workspace_manifest.py`:

1. **Root key** - created and kept **offline**. Its public half is installed with the
   client (installer / MDM) and is the only thing a client trusts a priori. The server
   never holds it.
2. **Signing certificate** - signed by the root; names one signing public key; valid
   for at most 90 days (default 30). Rotation = the root signs a new certificate. There
   is no step in which the server tells the client which key to trust.
3. **Manifest** - signed by the signing key; carries `company_id`, `person_id`,
   `aud`, a **monotonic `generation`**, `issued_at`/`expires_at` (lifetime at most
   24 h), `min_client_version`, an https `gateway_url`, the layout id and SHA-256, and
   for every mod its version and every file's path, size and SHA-256.

Rules the verifier applies, in this order, and a second (TypeScript) implementation
must reproduce `backend/tests/vectors/workspace_manifest_vectors.json`:

- optional **revocation list** (root-signed, `number` must not go backwards, revoked
  key ids are never un-revoked);
- certificate: root signature; `issuer_kid` equals the pinned root's id; the signing
  key's id is **recomputed** from its public key, never read from the document; time
  window with 5 minutes of skew;
- manifest signature with the certificate's key; shape and limits (names, relative
  paths without `..`, backslash, drive or NUL, case-insensitive duplicates, size and
  count caps, https gateway);
- bindings: `company_id`, `person_id` and `aud` must equal what the client already
  knows from its own session, never what the manifest says about itself;
- time: not expired, not from the future (beyond skew), and inside the certificate's
  window;
- **replay / rollback**: per `(company, person)` (stored under an unambiguous
  JSON-array key, not a joined string) the client stores the last accepted generation
  and digest. Lower generation is rejected; the same generation with a different digest
  is a conflict; the same digest is idempotent.
- **epoch (recovery)**: the certificate carries an `epoch` the root raises when a
  signing key may have been stolen, and the signed manifest repeats it (`epoch` must
  equal the certificate's, so an old signed payload cannot be re-wrapped in a newer
  epoch's certificate). A client that has seen epoch N refuses N-1, and a higher epoch
  restarts the generation floor, so a thief who pushed `generation` to the maximum cannot
  lock a person out for good. Only the root can raise it, and **recovery needs a new
  signing key**: a higher epoch certified for the same key is refused
  (`epoch_needs_new_key`), and the old key's id should also go into the next revocation
  list.
- **bootstrap floors are required**: when the client has no history for this person
  (empty state, or no entry for them) `Expected` must carry `min_generation`,
  `min_epoch` and `min_crl_number`, obtained over the authenticated session, otherwise the
  verifier raises `bootstrap_floor_required`; it never starts from zero by default. A
  first-ever enrolment passes 1, 1 and 0. The floors come from the session, never from the
  manifest. A generation or epoch floor does **not** carry the set of revoked keys, so the
  CRL floor is a separate checkpoint (a revocation-list number): a client shown only a
  late, empty list is refused with `crl_below_floor` when the floor says a newer list
  exists. This is only as good as the checkpoint the server hands out, and the root must
  keep publishing cumulative lists.
- **clock**: the highest clock reading accepted is stored and the clock may not go
  back beyond the skew (`clock_rollback`). Setting the clock back to revive an expired
  manifest is therefore detected as long as the state survives; a deleted state file is
  the bootstrap case above.
- **revocation lists** are root-signed, **cumulative** full snapshots (a list that drops
  a previously revoked key is refused), carry `issued_at` and `next_update`, may skip
  numbers, and the same number with different content is a conflict. The client ingests
  and persists a list **on its own, before checking any manifest** (`verify_crl`), so a
  revocation is not lost when the manifest is rejected; `ManifestError.state` also
  returns the state reached. `require_crl` makes the client refuse to accept a
  manifest if it has seen no list or the last one is past `next_update`.

Signatures are **domain separated** (`fab-signing-cert-v1`, `fab-crl-v1`,
`fab-workspace-manifest-v1` prefixes), so one document type cannot be presented as
another.

**Canonical profile** (a second implementation must match byte for byte; the vectors
file has cases for each rule): object keys sorted by **UTF-16 code unit** order (the
RFC 8785 and JavaScript order, which differs from code point order for characters
above U+FFFF); no whitespace; every character outside U+0020-U+007E escaped, as `\n`
`\r` `\t` `\b` `\f` or lower-case `\u00xx` / `\uxxxx` (surrogate pairs for
non-BMP), so there is no Unicode normalisation question and DEL (U+007F) is escaped
too; no floats; integers within +/-(2^53-1) and never `-0`; lone surrogates rejected;
depth at most 32. Untrusted bytes go through a strict parser first (`parse_wire`):
size cap (256 KiB), duplicate keys, floats and exponent forms, `-0`, NaN/Infinity,
out-of-range integers and lone surrogates are rejected rather than resolved
differently by each parser. Signed documents have no free-form room: unknown fields
are rejected at every level.

The provisioner then, for each file, downloads it, checks size and SHA-256
(`verify_file`), stages it in a temporary directory with traversal and symlink
rejection, and activates the whole set atomically. Verification in this module never
installs anything. These are requirements on the provisioner, not something this
module does: the state it returns (generation per person, epoch, signing key id,
revocation list, last clock reading) must be written atomically under a lock, mode 0600,
and persisted even when a manifest is rejected (`ManifestError.state`). The same OS user
can still delete it, which is why the bootstrap floors are mandatory.

**Portable names.** Paths, mod names and layout ids must be valid on Windows, macOS and
Linux: no `..`, absolute, backslash, drive or alternate-stream colon, control
characters or `<>"|?*`; no Windows device names (`CON`, `NUL`, `COM1`... with any
extension); no trailing dot or space; NFC only; each component at most 255 UTF-8 bytes;
two paths that are equal after NFC and case folding collide, and a file and a directory
of the same name cannot coexist. Sizes of the layout and every mod file count against a
256 MiB total; a manifest has at most 64 mods and 512 files per mod. The provisioner
still has to resolve real paths and refuse symlinks and reparse points when it writes.

## What this does not do

- It does not stop a user from adding their own mods, or running another Herdr
  instance (ADR-0026 decision 4: drift is a diagnostic signal).
- The 24 h manifest lifetime bounds only the replay of a manifest someone already has.
  If a **signing key is stolen**, the thief can sign fresh manifests until the
  certificate expires (at most 90 days, 30 by default) unless the client has a current
  revocation list; use `require_crl` to make that bound `next_update` instead, and raise
  the epoch (with a new key) to recover. A cold-start client that is shown only a late,
  empty list cannot tell it from a clean history without the CRL checkpoint above.
- A compromised root key is recovered only by re-pinning a new root on every client
  (reinstall or MDM push). Keeping the root offline is an **operating rule**, not
  something the code can enforce: `root-init` and `issue-*` will run anywhere. The
  server installer must therefore accept only the root *public* key and an
  offline-issued certificate, and must never be given the root private key.
- It assumes the pinned root public key itself was installed by a trusted channel
  (installer / MDM). The older `wellknown` endpoint and CLI are not yet migrated to
  this module.
- Authorisation is not in the manifest. The server re-checks person, tenant and role on
  every call (ADR-0026 decision 5); a valid manifest grants nothing by itself.

## Options considered

- **Single server key, pinned at install.** Fewer parts, but any rotation or leak
  means touching every client. Rejected for installations with more than a few users.
- **Fix the re-pin flow.** It would still need an authority above the server key;
  that authority is the root here.
- **TLS only.** Does not protect against a malicious or compromised server or
  intermediary that terminates TLS, and gives no per-file integrity or replay bound.

## Consequences

- Server setup gains one offline step (`scripts/manifest_keys.py root-init`, then
  `issue-cert`); `signing-init` runs on the server. The installer (ADR-0026
  deliverable 1) must walk through it and print the root public key for MDM.
- The `3pa` provisioner needs a TypeScript verifier against the shared vectors and a
  small state file (last generation per person, CRL number, revoked ids), mode 0600.
- Next slices: `GET /me/workspace` building manifests from role mapping; the
  provisioner; the signed-in session supplying `Expected` values.
