#!/usr/bin/env python3
"""Key tooling for the signed workspace manifest (ADR-0027).

The ROOT key is created and used on an offline machine. The server only ever holds
the SIGNING key and the root-signed certificate for it.

    # offline, once: make the root key; keep root.key safe, distribute root.pub
    python scripts/manifest_keys.py root-init --out root.key
    # on the server: make the signing key, print its public half
    python scripts/manifest_keys.py signing-init --out data/.workspace_signing_ed25519
    # offline: certify that public key (default 30 days; max 90)
    python scripts/manifest_keys.py issue-cert --root root.key --signing-pub <b64> \\
        --serial 1 --out workspace_signing.cert.json
    # offline: revoke signing keys (number must grow each time)
    python scripts/manifest_keys.py issue-crl --root root.key --number 1 --revoke <kid> --out crl.json
    # a later list carries earlier revocations over: add --previous crl.json (it is cumulative)

Run root-init and issue-* only on the offline machine; the server installer must never be
given root.key, only the public key and the certificate. Existing files are never
overwritten, and a private key that is group/world readable or a symlink is refused.

Private key files are written 0600 and never printed. Only public data goes to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import workspace_manifest as wm  # noqa: E402


def _write_new(path: str, text: str, mode: int) -> None:
    """Create a new file, never overwrite or follow an existing path (O_EXCL)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def _read_private(path: str) -> str:
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        raise SystemExit(f"{path}: not a regular file (symlinks are refused)")
    if st.st_mode & 0o077 or st.st_uid != os.geteuid():
        raise SystemExit(f"{path}: private key must be owner-only (0600) and yours")
    return Path(path).read_text().strip()


def _check_out_is_not_input(out: str, *inputs: str) -> None:
    o = Path(out).resolve()
    if any(o == Path(i).resolve() for i in inputs):
        raise SystemExit("--out must not be the same file as an input key")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("root-init", "signing-init"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)

    c = sub.add_parser("issue-cert")
    c.add_argument("--root", required=True)
    c.add_argument("--signing-pub", required=True)
    c.add_argument("--serial", type=int, required=True)
    c.add_argument(
        "--epoch",
        type=int,
        default=1,
        help="raise to recover from a stolen signing key",
    )
    c.add_argument("--days", type=int, default=30, help="1..90")
    c.add_argument("--out", required=True)

    r = sub.add_parser("issue-crl")
    r.add_argument("--root", required=True)
    r.add_argument("--number", type=int, required=True)
    r.add_argument("--revoke", action="append", default=[])
    r.add_argument(
        "--previous", help="previous CRL file; its revocations are carried over"
    )
    r.add_argument("--valid-days", type=int, default=7, help="next_update, 1..90")
    r.add_argument("--out", required=True)

    a = ap.parse_args(argv)
    now = int(time.time())

    if a.cmd in ("root-init", "signing-init"):
        priv, pub = wm.generate_key()
        _write_new(a.out, priv + "\n", 0o600)
        print(json.dumps({"public_key": pub, "key_id": wm.key_id(pub)}))
    elif a.cmd == "issue-cert":
        if not 1 <= a.days <= 90:
            raise SystemExit("--days must be 1..90")
        _check_out_is_not_input(a.out, a.root)
        cert = wm.issue_signing_cert(
            _read_private(a.root),
            a.signing_pub,
            not_before=now,
            not_after=now + a.days * 86400,
            serial=a.serial,
            epoch=a.epoch,
        )
        _write_new(a.out, json.dumps(cert, indent=2, sort_keys=True) + "\n", 0o644)
        print(
            json.dumps(
                {
                    "kid": cert["payload"]["kid"],
                    "epoch": a.epoch,
                    "not_after": cert["payload"]["not_after"],
                }
            )
        )
    else:
        if not 1 <= a.valid_days <= 90:
            raise SystemExit("--valid-days must be 1..90")
        _check_out_is_not_input(a.out, a.root, *([a.previous] if a.previous else []))
        revoked = set(a.revoke)
        if a.previous:
            revoked |= set(
                json.loads(Path(a.previous).read_text())["payload"]["revoked_kids"]
            )
        crl = wm.issue_crl(
            _read_private(a.root),
            number=a.number,
            revoked_kids=sorted(revoked),
            issued_at=now,
            next_update=now + a.valid_days * 86400,
        )
        _write_new(a.out, json.dumps(crl, indent=2, sort_keys=True) + "\n", 0o644)
        print(json.dumps({"number": a.number, "revoked": len(revoked)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
