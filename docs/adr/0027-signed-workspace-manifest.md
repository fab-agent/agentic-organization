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
- **replay / rollback**: per `(company, person)` the client stores the last accepted
  generation and digest. Lower generation is rejected; the same generation with a
  different digest is a conflict; the same digest is idempotent.

Signatures are **domain separated** (`fab-signing-cert-v1`, `fab-crl-v1`,
`fab-workspace-manifest-v1` prefixes), so one document type cannot be presented as
another. Canonical form: sorted keys, no whitespace, ASCII-only escapes, no floats,
integers within +/-2^53, depth at most 32.

The provisioner then, for each file, downloads it, checks size and SHA-256
(`verify_file`), stages it in a temporary directory with traversal and symlink
rejection, and activates the whole set atomically. Verification in this module never
installs anything.

## What this does not do

- It does not stop a user from adding their own mods, or running another Herdr
  instance (ADR-0026 decision 4: drift is a diagnostic signal).
- Revocation is as fresh as the last revocation list the client saw; the hard bound is
  the manifest lifetime (24 h) and the certificate lifetime (30 days by default).
- A compromised root key is recovered only by re-pinning a new root on every client
  (reinstall or MDM push). Keeping the root offline is the mitigation.
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
