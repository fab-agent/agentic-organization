"""
Ed25519 signing for the served opencode org config (ADR-0011).

`3pa` pins the public key on first setup and refuses to run a config bundle whose
signature does not verify. The private key lives at `data/.wellknown_ed25519`
(generated once, 0600), like the Fernet key in `core/security.py`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_KEY_FILE = pathlib.Path("data/.wellknown_ed25519")


def _private_key() -> Ed25519PrivateKey:
    if not _KEY_FILE.exists():
        _KEY_FILE.parent.mkdir(exist_ok=True)
        key = Ed25519PrivateKey.generate()
        _KEY_FILE.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        _KEY_FILE.chmod(0o600)
    return Ed25519PrivateKey.from_private_bytes(_KEY_FILE.read_bytes())


def public_key_b64() -> str:
    raw = (
        _private_key()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return base64.b64encode(raw).decode()


def key_id() -> str:
    """Short fingerprint of the public key, for pinning UX."""
    raw = base64.b64decode(public_key_b64())
    return hashlib.sha256(raw).hexdigest()[:16]


def canonical(config: dict) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_config(config: dict) -> str:
    sig = _private_key().sign(canonical(config).encode())
    return base64.b64encode(sig).decode()
