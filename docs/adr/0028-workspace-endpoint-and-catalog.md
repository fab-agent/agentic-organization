# ADR-0028: `GET /me/workspace` - role-based profile, catalog and manifest issuance

- **Status:** proposed
- **Date:** 2026-11-01
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (decisions 1, 3, 5), ADR-0027 (signed manifest)

## Context

ADR-0027 defines what a client verifies. Something on the server has to decide which
layout and mods a person gets, hand out files, allocate generations, and sign. It has to
fail closed, keep tenants apart, and not become a way to reach other people's files.

## Decision

**Endpoints** (all need a signed-in human session; the person is never taken from the
request):

- `GET /me/workspace?company_id=` -> `{manifest, bootstrap}`. `manifest` is the ADR-0027
  envelope; `bootstrap` is `{min_generation, min_epoch, min_crl_number}` for a client with
  no history (they equal the generation just issued, the signing epoch and the current
  revocation-list number; they authenticate through the session, not the signature).
- `GET /me/workspace/files/{sha256}` -> the bytes, only if the hash belongs to the
  caller's own current profile (layout or a mod file); `private, no-store`, `nosniff`.
- `GET /me/workspace/crl` -> the root-signed cumulative list, when one is published.

**Who the person is.** The user's own human `Personnel` row in the requested company
(membership checked, as for `/assistant`). No linked person, an agent record, or a
company the user is not a member of gets 404/403 and nothing is signed.

**Profiles.** `catalog/profiles.json` lists profiles in order; the first whose `match`
holds wins, else `defaults`, else no workspace. `match` keys (all must hold, each is
any-of): `roles` (the user's `CompanyMember` roles in that company), `departments` (ids
or slugs of the person's department **and its ancestors**), `companies`. A profile names
a layout and a list of `{name, version}` mods. Unknown keys are an error, not ignored.
A UI to edit profiles is a later slice; today the file is deployed with the catalog.

**Catalog.** `catalog/layouts/<id>.json` and `catalog/mods/<name>/<version>/**` under
`WORKSPACE_DIR` (default `data/workspace`). Files are opened once with `O_NOFOLLOW` and
checked on the descriptor; any symlink or special file inside the catalog refuses the
whole request. Hashes and sizes are computed from the bytes at issue time; a file that
changed between listing and download is not served.

**Signing material.** `root.pub` (or `WORKSPACE_ROOT_PUB`), `signing.key` (0600, owner
only), `signing.cert.json`, optional `crl.json`. The server checks, on every issue, that
the certificate verifies under the pinned root, is inside its window, belongs to the key
on disk, and is not revoked by the list it serves. The server never generates a root key
or a certificate (ADR-0027: the root is offline).

**Generations.** One row per `(company, person)` in `workspacemanifeststate`;
allocation is compare-and-set on the stored value with a unique key against double
creation, retried a bounded number of times. Each issue takes a new generation, so a
re-issued manifest is never the "same generation, different content" conflict. A higher
signing epoch restarts the count at 1; a server whose epoch is lower than the stored one
refuses (misconfiguration or rollback).

**Gateway URL.** The `gateway_url` the manifest signs tells the client where to send
every model call, so it comes only from operator configuration (`workstation.base_url`,
else `PUBLIC_BASE_URL` / `WORKSTATION_BASE_URL`). The request's `Host` and
`X-Forwarded-*` headers are never used, and with nothing configured the endpoint refuses
(`gateway_url_not_configured`) instead of guessing. It must be `https`.

**Fail closed.** Any of: missing/invalid signing material, catalog or profile error,
non-https gateway URL, audit write failure, generation contention -> `503
workspace_unavailable` with a stable value-free `reason` and `Retry-After`, and no
manifest. Issuing is audited (`workspace_manifest_issued`: person, profile, layout, mods,
generation, epoch, signing key id; no file contents or keys) and the manifest is withheld
if the record cannot be written, because it hands out code to run.

## Consequences

- Operating the server now includes the offline step of ADR-0027 and deploying the
  catalog; the installer (ADR-0026 deliverable 1) must create `data/workspace` with the
  right modes and refuse to start the feature without the root public key.
- A generation is consumed even if the response is lost; gaps are fine (the client only
  needs growth).
- Not in this slice: the provisioner and TypeScript verifier, catalog/profile admin UI,
  per-mod size accounting beyond the manifest limits, rate limiting of this endpoint,
  caching of resolved profiles, migration of the old `wellknown` flow.
