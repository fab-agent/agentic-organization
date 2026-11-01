"""
Signed workspace manifest (ADR-0027, part of ADR-0026 decision 3).

What a client (the `3pa` provisioner) may install into a Herdr app home is decided by
a manifest the server signs. Trust chain:

    root key (offline, public half pinned by the installer / MDM)
      -> signing certificate (root-signed, short lived, names the signing key)
        -> manifest (signed by the signing key; hashes of the layout and every mod file)

The root key never lives on the server. Rotation is a new certificate signed by the root;
there is no "the server tells you its previous key" step (the flaw of the older
`wellknown` re-pin flow, which an attacker who can alter responses could forge).

Everything here is pure: `verify_manifest` takes the clock and the client's stored
state and returns the new state; the caller persists it. A second implementation (the
TypeScript client) must reproduce `tests/vectors/workspace_manifest_vectors.json`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# Domain separation: a signature made for one document type can never verify as
# another, or as any other Ed25519 use in this codebase.
_DOMAIN = {
    "cert": b"fab-signing-cert-v1\n",
    "crl": b"fab-crl-v1\n",
    "manifest": b"fab-workspace-manifest-v1\n",
}

MAX_MANIFEST_LIFETIME = 24 * 3600  # seconds
MAX_CERT_LIFETIME = 90 * 24 * 3600
CLOCK_SKEW = 300
MAX_MODS = 64
MAX_FILES_PER_MOD = 512
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_JSON_DEPTH = 32
_MAX_SAFE_INT = 2**53 - 1  # what a JavaScript client can represent exactly

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_VERSION = re.compile(r"^\d{1,6}\.\d{1,6}\.\d{1,6}$")


class ManifestError(Exception):
    """Verification or construction failed. `code` is stable and value-free."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── canonical bytes ──────────────────────────────────────────────────────────


def _check_json(obj: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ManifestError("too_deep")
    if obj is None or isinstance(obj, (str, bool)):
        return
    if isinstance(obj, int):
        if abs(obj) > _MAX_SAFE_INT:
            raise ManifestError("int_out_of_range")
        return
    if isinstance(obj, list):
        for v in obj:
            _check_json(v, depth + 1)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ManifestError("non_string_key")
            _check_json(v, depth + 1)
        return
    raise ManifestError("unsupported_type")  # floats included: no cross-language form


def canonical_bytes(obj: Any) -> bytes:
    """Sorted keys, no whitespace, ASCII-only escapes (so no Unicode normalisation
    question), no floats, integers within +/-2^53. Reproducible in any language."""
    _check_json(obj)
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _signed_bytes(kind: str, payload: dict) -> bytes:
    return _DOMAIN[kind] + canonical_bytes(payload)


def digest(payload: dict) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


# ── keys ─────────────────────────────────────────────────────────────────────


def _pub_raw(priv: Ed25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )


def generate_key() -> tuple[str, str]:
    """(private_b64, public_b64) of a fresh Ed25519 key."""
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode(), base64.b64encode(_pub_raw(priv)).decode()


def load_private(private_b64: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))


def key_id(public_b64: str) -> str:
    """Recomputed from the public key by every verifier; never taken on trust."""
    return hashlib.sha256(base64.b64decode(public_b64)).hexdigest()[:32]


def _verify_sig(public_b64: str, kind: str, payload: dict, sig_b64: str) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64)).verify(
            base64.b64decode(sig_b64), _signed_bytes(kind, payload)
        )
    except (InvalidSignature, ValueError, TypeError) as e:
        raise ManifestError("bad_signature") from e


def _sign(private_b64: str, kind: str, payload: dict) -> str:
    return base64.b64encode(
        load_private(private_b64).sign(_signed_bytes(kind, payload))
    ).decode()


# ── root-signed documents ────────────────────────────────────────────────────


def issue_signing_cert(
    root_private_b64: str,
    signing_public_b64: str,
    *,
    not_before: int,
    not_after: int,
    serial: int,
) -> dict:
    """Run offline with the root key. The server only ever receives the result."""
    if not 0 < not_after - not_before <= MAX_CERT_LIFETIME:
        raise ManifestError("cert_lifetime")
    root_pub = base64.b64encode(_pub_raw(load_private(root_private_b64))).decode()
    payload = {
        "typ": "fab-signing-cert",
        "v": 1,
        "kid": key_id(signing_public_b64),
        "pub": signing_public_b64,
        "issuer_kid": key_id(root_pub),
        "not_before": not_before,
        "not_after": not_after,
        "serial": serial,
    }
    return {"payload": payload, "sig": _sign(root_private_b64, "cert", payload)}


def issue_crl(
    root_private_b64: str, *, number: int, revoked_kids: list[str], issued_at: int
) -> dict:
    payload = {
        "typ": "fab-crl",
        "v": 1,
        "number": number,
        "revoked_kids": sorted(revoked_kids),
        "issued_at": issued_at,
    }
    return {"payload": payload, "sig": _sign(root_private_b64, "crl", payload)}


# ── manifest construction (server) ───────────────────────────────────────────


def _safe_path(path: Any) -> str:
    if (
        not isinstance(path, str)
        or not path
        or len(path) > 200
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or ":" in path
    ):
        raise ManifestError("bad_path")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ManifestError("bad_path")
    return path


def _validate_body(p: dict) -> None:
    """Shape and limits of a manifest payload. Used when building and verifying."""
    for k in ("company_id", "person_id", "aud"):
        if not isinstance(p.get(k), str) or not p[k] or len(p[k]) > 128:
            raise ManifestError("bad_binding")
    if not isinstance(p.get("generation"), int) or p["generation"] < 1:
        raise ManifestError("bad_generation")
    for k in ("issued_at", "expires_at"):
        if not isinstance(p.get(k), int) or p[k] < 0:
            raise ManifestError("bad_time")
    if not 0 < p["expires_at"] - p["issued_at"] <= MAX_MANIFEST_LIFETIME:
        raise ManifestError("bad_lifetime")
    if not isinstance(p.get("min_client_version"), str) or not _VERSION.match(
        p["min_client_version"]
    ):
        raise ManifestError("bad_version")
    gw = p.get("gateway_url")
    if not isinstance(gw, str) or not gw.startswith("https://") or len(gw) > 300:
        raise ManifestError("bad_gateway_url")
    layout = p.get("layout")
    if (
        not isinstance(layout, dict)
        or not _NAME.match(str(layout.get("id", "")))
        or not _SHA256.match(str(layout.get("sha256", "")))
    ):
        raise ManifestError("bad_layout")
    mods = p.get("mods")
    if not isinstance(mods, list) or len(mods) > MAX_MODS:
        raise ManifestError("bad_mods")
    seen_mods: set[str] = set()
    total = 0
    for m in mods:
        if not isinstance(m, dict) or not _NAME.match(str(m.get("name", ""))):
            raise ManifestError("bad_mod")
        if m["name"] in seen_mods:
            raise ManifestError("duplicate_mod")
        seen_mods.add(m["name"])
        if not _VERSION.match(str(m.get("version", ""))):
            raise ManifestError("bad_mod")
        files = m.get("files")
        if not isinstance(files, list) or not files or len(files) > MAX_FILES_PER_MOD:
            raise ManifestError("bad_mod_files")
        seen_paths: set[str] = set()
        for f in files:
            if not isinstance(f, dict):
                raise ManifestError("bad_mod_files")
            path = _safe_path(f.get("path"))
            if path.lower() in seen_paths:  # case-insensitive filesystems
                raise ManifestError("duplicate_path")
            seen_paths.add(path.lower())
            if not _SHA256.match(str(f.get("sha256", ""))):
                raise ManifestError("bad_hash")
            size = f.get("size")
            if not isinstance(size, int) or size < 0:
                raise ManifestError("bad_size")
            total += size
    if total > MAX_TOTAL_BYTES:
        raise ManifestError("too_large")


def sign_manifest(signing_private_b64: str, cert: dict, payload: dict) -> dict:
    """Server side. Refuses to sign a body that would not verify."""
    body = {"typ": "fab-workspace-manifest", "v": 1, **payload}
    _validate_body(body)
    if cert["payload"]["kid"] != key_id(
        base64.b64encode(_pub_raw(load_private(signing_private_b64))).decode()
    ):
        raise ManifestError("cert_key_mismatch")
    return {
        "cert": cert,
        "payload": body,
        "sig": _sign(signing_private_b64, "manifest", body),
    }


# ── verification (client) ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Expected:
    """What the client already knows from its own session, never from the manifest."""

    company_id: str
    person_id: str
    aud: str  # e.g. "herdr-provisioner"
    client_version: str = "0.0.0"


@dataclass(frozen=True)
class ClientState:
    """Persisted by the client after each accepted manifest or CRL."""

    generations: dict[str, dict[str, Any]] = field(default_factory=dict)
    crl_number: int = 0
    revoked: frozenset[str] = frozenset()


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def verify_crl(crl: dict, root_pub_b64: str, state: ClientState) -> ClientState:
    p = crl.get("payload")
    if not isinstance(p, dict) or p.get("typ") != "fab-crl" or p.get("v") != 1:
        raise ManifestError("bad_crl")
    _verify_sig(root_pub_b64, "crl", p, crl.get("sig", ""))
    if not isinstance(p.get("number"), int) or not isinstance(
        p.get("revoked_kids"), list
    ):
        raise ManifestError("bad_crl")
    if p["number"] < state.crl_number:
        raise ManifestError("crl_rollback")
    return ClientState(
        generations=state.generations,
        crl_number=p["number"],
        revoked=state.revoked | frozenset(p["revoked_kids"]),
    )


def verify_manifest(
    envelope: dict,
    *,
    root_pub_b64: str,
    expected: Expected,
    now: int,
    state: ClientState,
    crl: dict | None = None,
) -> tuple[dict, ClientState]:
    """
    Returns `(payload, new_state)` or raises ManifestError. Order: revocation list,
    certificate (root signature, recomputed key id, window), manifest signature,
    bindings, time, replay/rollback. Nothing is installed by this function.
    """
    if crl is not None:
        state = verify_crl(crl, root_pub_b64, state)

    cert, payload = envelope.get("cert"), envelope.get("payload")
    if not isinstance(cert, dict) or not isinstance(payload, dict):
        raise ManifestError("malformed")
    cp = cert.get("payload")
    if (
        not isinstance(cp, dict)
        or cp.get("typ") != "fab-signing-cert"
        or cp.get("v") != 1
    ):
        raise ManifestError("bad_cert")
    _verify_sig(root_pub_b64, "cert", cp, cert.get("sig", ""))
    if cp.get("issuer_kid") != key_id(root_pub_b64):
        raise ManifestError("bad_cert")
    if cp.get("kid") != key_id(cp.get("pub", "")):
        raise ManifestError("bad_cert")
    nb, na = cp.get("not_before"), cp.get("not_after")
    if (
        not isinstance(nb, int)
        or not isinstance(na, int)
        or not 0 < na - nb <= MAX_CERT_LIFETIME
    ):
        raise ManifestError("bad_cert")
    if now + CLOCK_SKEW < nb or now - CLOCK_SKEW > na:
        raise ManifestError("cert_not_valid_now")
    if cp["kid"] in state.revoked:
        raise ManifestError("cert_revoked")

    if payload.get("typ") != "fab-workspace-manifest" or payload.get("v") != 1:
        raise ManifestError("malformed")
    _verify_sig(cp["pub"], "manifest", payload, envelope.get("sig", ""))
    _validate_body(payload)

    if (
        payload["company_id"] != expected.company_id
        or payload["person_id"] != expected.person_id
        or payload["aud"] != expected.aud
    ):
        raise ManifestError("wrong_binding")
    if _vtuple(expected.client_version) < _vtuple(payload["min_client_version"]):
        raise ManifestError("client_too_old")
    if now + CLOCK_SKEW < payload["issued_at"]:
        raise ManifestError("not_yet_valid")
    if now - CLOCK_SKEW > payload["expires_at"]:
        raise ManifestError("expired")
    # The manifest must also fall inside the certificate's window.
    if payload["issued_at"] < nb or payload["expires_at"] > na:
        raise ManifestError("outside_cert_window")

    key = f"{payload['company_id']}:{payload['person_id']}"
    d = digest(payload)
    last = state.generations.get(key)
    if last:
        if payload["generation"] < last["generation"]:
            raise ManifestError("rollback")
        if payload["generation"] == last["generation"] and d != last["digest"]:
            raise ManifestError("generation_conflict")
    gens = dict(state.generations)
    gens[key] = {"generation": payload["generation"], "digest": d}
    return payload, ClientState(gens, state.crl_number, state.revoked)


def verify_file(content: bytes, entry: dict) -> None:
    """The provisioner calls this for each downloaded file before staging it."""
    if len(content) != entry["size"]:
        raise ManifestError("size_mismatch")
    if hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise ManifestError("hash_mismatch")
