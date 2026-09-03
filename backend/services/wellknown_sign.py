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
_PREV_KEY_FILE = pathlib.Path("data/.wellknown_ed25519.prev")


def _raw_priv() -> bytes:
    return _KEY_FILE.read_bytes()


def _load_or_create() -> Ed25519PrivateKey:
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
    return Ed25519PrivateKey.from_private_bytes(_raw_priv())


def _private_key() -> Ed25519PrivateKey:
    return _load_or_create()


def _pub_b64(priv: Ed25519PrivateKey) -> str:
    raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def _fingerprint(pub_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(pub_b64)).hexdigest()[:16]


def public_key_b64() -> str:
    return _pub_b64(_private_key())


def key_id() -> str:
    """Short fingerprint of the public key, for pinning UX."""
    return _fingerprint(public_key_b64())


def previous_public_key_b64() -> str | None:
    """The just-rotated-out key, if any — served during the rotation grace window."""
    if not _PREV_KEY_FILE.exists():
        return None
    priv = Ed25519PrivateKey.from_private_bytes(_PREV_KEY_FILE.read_bytes())
    return _pub_b64(priv)


def previous_key_id() -> str | None:
    pub = previous_public_key_b64()
    return _fingerprint(pub) if pub else None


def rotate_key() -> dict:
    """
    Generate a fresh signing key. The old one is kept at `.prev` so `3pa` clients
    still pinned to it accept the transition and re-pin (ADR-0011). Call again to
    drop the previous key once every client has rolled over.
    """
    _load_or_create()  # ensure a current key exists
    old_kid = key_id()
    _PREV_KEY_FILE.write_bytes(_raw_priv())
    _PREV_KEY_FILE.chmod(0o600)
    new = Ed25519PrivateKey.generate()
    _KEY_FILE.write_bytes(
        new.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    _KEY_FILE.chmod(0o600)
    return {"previous_key_id": old_kid, "key_id": key_id()}


def drop_previous_key() -> bool:
    if _PREV_KEY_FILE.exists():
        _PREV_KEY_FILE.unlink()
        return True
    return False


def canonical(config: dict) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_config(config: dict) -> str:
    sig = _private_key().sign(canonical(config).encode())
    return base64.b64encode(sig).decode()
