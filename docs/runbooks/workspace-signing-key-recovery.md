# Runbook: workspace signing key lost, stolen or suspected

Applies to the signed workspace manifest (ADR-0027, ADR-0028). This page orders the steps; the
reasons are in those ADRs. Everything here is checked against `backend/scripts/manifest_keys.py`
and `backend/services/workspace_service.py`.

## Before you start

- Keep a **ledger offline** of everything ever issued: signing key ids, certificate serials and epochs, CRL numbers. Choose new epochs, serials and CRL numbers from the ledger, never from a restored database.
- Output files are never overwritten (the tool refuses). Use a new file name or a clean staging folder for each run.
- Commands are `python scripts/manifest_keys.py <command>` run from `backend/` (so `.venv/bin/python scripts/manifest_keys.py ...`).
- `GET /me/workspace` is limited to one per person per 10 s (ADR-0037). A checking call uses that person's slot: wait 10 s (30 s after a `503`) before running `3pa workspace sync` as the same person, or check with a different test person. A `429` there is not a signing failure.

## Who holds what

| Key | Where | If lost | If stolen |
| --- | --- | --- | --- |
| **Root** private key | Offline machine only (never on the server, never given to an installer) | No new certificates or revocation lists can be issued. The server keeps issuing short manifests (at most 24 h each) with the signing key and certificate it already has, until that certificate ends (at most 90 days); then it stops. Files already installed on laptops are not removed. Recovery = a new root, see E. | **Everyone who still pins the old root is exposed**: the thief can certify a new signing key at a higher epoch and sign manifests those clients accept. Containment, not a quiet swap: see E. |
| **Signing** private key (`WORKSPACE_DIR/signing.key`, mode 0600) | On the server | Server cannot sign: `503 workspace_unavailable`, clients keep what they have. Replace it (below). | **Raise the epoch with a new key and revoke the old one** (below). |

The server never creates a root key or a certificate. Only the root (offline) can certify a signing key.

## A. Signing key lost or unusable (not suspected stolen)

No one else holds it, so no revocation is needed, but the server cannot sign until a certified key exists.

1. On the server: `python scripts/manifest_keys.py signing-init --out <new path>`. Note the printed `public_key`.
2. Offline, with the root key: `python scripts/manifest_keys.py issue-cert --root root.key --signing-pub <public_key> --serial <next serial> --epoch <same epoch> --out signing.cert.json`.
   Use a **new key** every time, never the old one again. Serial numbers only grow; keep a ledger of every key id and serial you have issued.
3. Copy `signing.cert.json` to the server and put the new private key at `WORKSPACE_DIR/signing.key` (owner-only, mode 0600). Files are read on every request; no restart is needed.
4. Check: `GET /me/workspace` returns 200 and a client `3pa workspace sync` succeeds.

## B. Signing key stolen or suspected (act in this order)

1. **Stop the exposure now.** Remove `signing.key` from the server (or stop the feature). Clients keep their last installed workspace; no new one is handed out. This is safe: the server fails closed.
2. On the server: `signing-init` a fresh key, note its `public_key`.
3. Offline: raise the epoch by one. `issue-cert ... --serial <next> --epoch <old epoch + 1>` for the **new** public key. A client that has seen epoch N refuses N-1, and a higher epoch restarts its generation floor, so a thief who pushed generations high cannot lock anyone out.
   A client that knows the old key id refuses a higher epoch certified for the **same** key (`epoch_needs_new_key`): the key must really be new.
4. Offline: publish a **cumulative** revocation list containing the old key's id: `issue-crl --root root.key --number <previous number + 1> --revoke <old kid> --previous crl.json --out crl.json.new` (omit `--previous` only if no list was ever published). The number must be greater than the last one; a list that drops earlier revocations is refused by clients. CRL numbers stop at 2^53-1 (9007199254740991); `issue-crl` refuses a higher one. A list carries a `next_update` (`--valid-days`, default 7, max 90). The verifier can refuse a stale list (`require_crl`), but `3pa workspace sync` does not turn that on today, so staleness is not enforced on clients; still plan the next list before it ends.
5. On the server: install the new `signing.key`, `signing.cert.json` and `crl.json` (replace `crl.json` last). The server remembers the highest list number it has accepted and refuses to serve an older one (`crl_rollback`) or none after one was published (`crl_missing`).
6. Check: `GET /me/workspace` is 200 with the new epoch; `GET /me/workspace/crl` returns the new number; a client sync succeeds (`3pa workspace sync`).
7. Clients that have not synced yet still trust the old epoch until they see the new certificate or list. The next sync fetches the list first and then the manifest. Raising the epoch alone does not revoke the old key for a client that has not yet seen the new epoch or list, so ask people with long-offline machines to run `3pa workspace sync` once.
8. Record the incident: when it was noticed, which key id, which epoch and CRL number replaced it, who ran the offline steps. Look at the audit chain for `workspace_manifest_issued` events carrying the old `signing_kid` after the suspected time.

## C. A wrong, too-high CRL number was signed

The server keeps the highest valid list number it has accepted and **never lowers it**. Do not edit the stored mark. Publish a corrective list with an even higher number and the correct cumulative contents (`--previous` the wrong list is acceptable only if its revocations are right; otherwise list the correct kids with `--revoke`, understanding that clients refuse a list that drops a revocation they already hold).
**Limit:** the number cannot exceed 2^53-1. If that exact maximum was signed and accepted, there is **no supported recovery today**: a new root does not help, because the server's stored high-water mark is not tied to a root and the number range does not restart. This needs a deliberate, reviewed change to the server checkpoint (new ADR and code), not a runbook step. Do not lower the mark, delete the row or delete client state quietly; that removes the rollback protection for everyone. Prevention: take CRL numbers from the ledger, increase by one, and double-check the number before signing.

## D. Server database rows were lost (restore, manual delete)

Generation counters are per person. If they are gone, "never reused" no longer holds. Recover as in B: new key, epoch + 1 (from the ledger), which restarts every client's floor. The CRL checkpoint is stored too: put back the latest cumulative `crl.json` you issued (or publish a new one with a higher number) before serving, otherwise the server answers `crl_missing`/`crl_rollback`. That only happens while the stored high-water mark survives: if the mark was lost with the rows and no list is present, the server serves **without** a list and without any error, so do not rely on it to notice. Restore the latest cumulative list from the ledger and verify it by hand.

## E. Root key lost or stolen

Changing the root is a **new trust start**, not a rotation. Re-pinning does not erase anything a client or the server remembers: epoch, generations, revoked keys and CRL number stay, and a new root that starts at epoch 1 or CRL 1 is refused (`epoch_rollback`, `crl_rollback`, `crl_not_cumulative`, `signing_epoch_behind_state`). Nothing about it is automatic or quiet.

**Stolen root: contain first.** Until a client pins the new root, it accepts whatever the stolen root signs (a new signing key at a higher epoch and manifests the client accepts). There is no safe interim for those machines. Stop issuing workspaces from the server (remove `signing.key`), tell the people involved, and treat every machine that has not confirmed the new pin as untrusted for workspace content until it has.

**Lost root (not stolen):** the old root cannot issue anything, so the same migration is needed before the current certificate ends.

1. Offline: `root-init` a new root key; keep it offline; record its public key and key id in the ledger and confirm that fingerprint with people **out of band** (not through the same channel that delivers the pin).
2. Server: set the new root public key where the server reads it (`WORKSPACE_ROOT_PUB` wins over `root.pub` if set; restart the process if it comes from the environment). Install a new signing key and a certificate issued under the new root, with an epoch **above the highest the server has issued** (its stored state refuses a lower one; take it from the ledger). Do not try to outrun client floors: after a root theft a client may have been pushed to any epoch, up to the protocol maximum, and step 3 resets that client history deliberately. If the server's own trusted epoch is already at the maximum (2^53-1) there is no higher epoch and no supported recovery today, as for the CRL limit in C, and a CRL number above the last published, signed by the new root and listing every previously revoked key (the tool cannot carry the old root's list over with `--previous`; list the kids with `--revoke`).
3. Clients: replace the pin (`installers/user ... --replace-root`, or MDM, `installers/deploy`) **and** reset the local sync state with a deliberate `3pa workspace sync --re-enroll`. `--replace-root` alone only changes the pin file.
4. Track completion per machine with something that identifies the device: your MDM or inventory output, or direct confirmation of the pinned fingerprint. The monitoring page is a diagnostic signal only: it keeps one self-reported line per person (no device id, no root fingerprint), so it cannot show that a machine pinned the new root. Keep a machine untrusted until it is confirmed that way; never release it on a self-report.

## What this does not cover

- Windows/macOS code signing of the installers and the CLI release signature key (ADR-0031): the release chain has its own rotation, which is manual today.
- Detecting that a key was stolen. Nothing here notices; look at the audit chain and at where the key was stored.
