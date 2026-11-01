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

Private key files are written 0600 and never printed. Only public data goes to stdout.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import workspace_manifest as wm  # noqa: E402


def _write_private(path: str, private_b64: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(private_b64 + "\n")


def _read_private(path: str) -> str:
    return Path(path).read_text().strip()


def _pub_of(private_b64: str) -> str:
    return base64.b64encode(wm._pub_raw(wm.load_private(private_b64))).decode()


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
    c.add_argument("--days", type=int, default=30)
    c.add_argument("--out", required=True)

    r = sub.add_parser("issue-crl")
    r.add_argument("--root", required=True)
    r.add_argument("--number", type=int, required=True)
    r.add_argument("--revoke", action="append", default=[])
    r.add_argument("--out", required=True)

    a = ap.parse_args(argv)
    now = int(time.time())

    if a.cmd in ("root-init", "signing-init"):
        priv, pub = wm.generate_key()
        _write_private(a.out, priv)
        print(json.dumps({"public_key": pub, "key_id": wm.key_id(pub)}))
    elif a.cmd == "issue-cert":
        cert = wm.issue_signing_cert(
            _read_private(a.root),
            a.signing_pub,
            not_before=now - 300,
            not_after=now + a.days * 86400,
            serial=a.serial,
        )
        Path(a.out).write_text(json.dumps(cert, indent=2, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    "kid": cert["payload"]["kid"],
                    "not_after": cert["payload"]["not_after"],
                }
            )
        )
    else:
        crl = wm.issue_crl(
            _read_private(a.root), number=a.number, revoked_kids=a.revoke, issued_at=now
        )
        Path(a.out).write_text(json.dumps(crl, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"number": a.number, "revoked": sorted(a.revoke)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
