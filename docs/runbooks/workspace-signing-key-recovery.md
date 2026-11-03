# Runbook: workspace signing key lost, stolen or suspected

Applies to the signed workspace manifest (ADR-0027, ADR-0028). This page orders the steps; the
reasons are in those ADRs. Everything here is checked against `backend/scripts/manifest_keys.py`
and `backend/services/workspace_service.py`.

## Who holds what

| Key | Where | If lost | If stolen |
| --- | --- | --- | --- |
| **Root** private key | Offline machine only (never on the server, never given to an installer) | Cannot issue anything new. Existing manifests keep working until the certificate expires (at most 90 days). Recovery = new root, **re-pinned on every client** (reinstall or MDM push). | Same as lost, and treat every signed artifact as untrusted: re-pin a new root everywhere. |
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
4. Offline: publish a **cumulative** revocation list containing the old key's id: `issue-crl --root root.key --number <previous number + 1> --revoke <old kid> --previous crl.json --out crl.json.new` (omit `--previous` only if no list was ever published). The number must be greater than the last one; a list that drops earlier revocations is refused by clients. A list carries a `next_update` (`--valid-days`, default 7, max 90). The verifier can refuse a stale list (`require_crl`), but `3pa workspace sync` does not turn that on today, so staleness is not enforced on clients; still plan the next list before it ends.
5. On the server: install the new `signing.key`, `signing.cert.json` and `crl.json` (replace `crl.json` last). The server remembers the highest list number it has accepted and refuses to serve an older one (`crl_rollback`) or none after one was published (`crl_missing`).
6. Check: `GET /me/workspace` is 200 with the new epoch; `GET /me/workspace/crl` returns the new number; a client sync succeeds (`3pa workspace sync`).
7. Clients that have not synced yet still trust the old epoch until they see the new certificate or list. The next sync fetches the list first and then the manifest. Raising the epoch alone does not revoke the old key for a client that has not yet seen the new epoch or list, so ask people with long-offline machines to run `3pa workspace sync` once.
8. Record the incident: when it was noticed, which key id, which epoch and CRL number replaced it, who ran the offline steps. Look at the audit chain for `workspace_manifest_issued` events carrying the old `signing_kid` after the suspected time.

## C. A wrong, too-high CRL number was signed

The server keeps the highest valid list number it has accepted and **never lowers it**. Do not edit the stored mark. Publish a corrective list with an even higher number and the correct cumulative contents.

## D. Server database rows were lost (restore, manual delete)

Generation counters are per person. If they are gone, "never reused" no longer holds. Recover as in B: new key, epoch + 1. This restarts every client's floor.

## E. Root key lost or stolen

1. Offline: `root-init` a new root key, store it offline. Print `public_key` and its key id.
2. Re-pin the new root public key on every client by reinstalling (`installers/user`, `--replace-root`) or pushing it through MDM (`installers/deploy`, see its README).
3. Issue a new signing cert under the new root (epoch can restart; clients that were re-pinned have no history under the new root).
4. Until a client has the new root pinned it will refuse the new certificate. Plan for that window; nothing unsafe is accepted in the meantime.

## What this does not cover

- Windows/macOS code signing of the installers and the CLI release signature key (ADR-0031): the release chain has its own rotation, which is manual today.
- Detecting that a key was stolen. Nothing here notices; look at the audit chain and at where the key was stored.
