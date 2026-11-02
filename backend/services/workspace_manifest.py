"""
Signed workspace manifest (ADR-0027, part of ADR-0026 decision 3).

What a client (the `3pa` provisioner) may install into a Herdr app home is decided by
a manifest the server signs. Trust chain:

    root key (offline, public half pinned by the installer / MDM)
      -> signing certificate (root-signed, short lived, names the signing key + epoch)
        -> manifest (signed by the signing key; hashes of the layout and every mod file)

The root key never lives on the server. Rotation is a new certificate signed by the root;
there is no "the server tells you its previous key" step (the flaw of the older
`wellknown` re-pin flow, which an attacker who can alter responses could forge).

Everything here is pure: `verify_manifest` takes the clock and the client's stored
state and returns the new state; the caller persists it. A second implementation (the
TypeScript client) must reproduce `tests/vectors/workspace_manifest_vectors.json`.

Canonical profile (also in ADR-0027): JSON with object keys sorted by UTF-16 code unit
order (the RFC 8785 / JavaScript order, so a JS client sorts the same way), no
whitespace, every non-ASCII character escaped as lower-case `\\uXXXX` (so no Unicode
normalisation question), no floats, integers within +/-(2^53-1) and never `-0`,
duplicate keys and lone surrogates rejected, depth at most 32.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

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
MAX_TOTAL_BYTES = 256 * 1024 * 1024  # layout + all mod files
MAX_JSON_DEPTH = 32
MAX_WIRE_BYTES = 256 * 1024  # one envelope on the wire
MAX_CRL_ENTRIES = 10_000
_MAX_SAFE_INT = 2**53 - 1  # what a JavaScript client can represent exactly

_SHA256 = re.compile(r"[0-9a-f]{64}")
_KID = re.compile(r"[0-9a-f]{32}")
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_VERSION = re.compile(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}")
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_RESERVED = {"con", "prn", "aux", "nul"} | {
    f"{d}{i}" for d in ("com", "lpt") for i in range(1, 10)
}


class ManifestError(Exception):
    """Verification or construction failed. `code` is stable and value-free.
    `state` carries the client state reached before the failure (for example a
    revocation list that was accepted), so the caller can persist it."""

    def __init__(self, code: str, state: ClientState | None = None):
        super().__init__(code)
        self.code = code
        self.state = state


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _v1(x: Any) -> bool:
    return (
        _is_int(x) and x == 1
    )  # True == 1 in Python; a signed `v` must be the integer 1


# ── canonical bytes and strict wire parsing ──────────────────────────────────


def _check_str(s: str) -> None:
    if any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        raise ManifestError("bad_string")  # lone surrogate: not a Unicode scalar string


def _check_json(obj: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ManifestError("too_deep")
    if obj is None or isinstance(obj, bool):
        return
    if isinstance(obj, str):
        _check_str(obj)
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
            _check_str(k)
            _check_json(v, depth + 1)
        return
    raise ManifestError("unsupported_type")  # floats included: no cross-language form


def _ser(obj: Any) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=True)
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, list):
        return "[" + ",".join(_ser(v) for v in obj) + "]"
    keys = sorted(obj, key=lambda k: k.encode("utf-16-be"))  # UTF-16 code unit order
    return (
        "{"
        + ",".join(json.dumps(k, ensure_ascii=True) + ":" + _ser(obj[k]) for k in keys)
        + "}"
    )


def canonical_bytes(obj: Any) -> bytes:
    _check_json(obj)
    return _ser(obj).encode("ascii")


def parse_wire(data: bytes | str, max_bytes: int = MAX_WIRE_BYTES) -> Any:
    """Parse untrusted JSON under the canonical profile: size cap, duplicate keys,
    floats, exponent forms, `-0`, NaN/Infinity, out-of-range integers and lone
    surrogates are all rejected instead of being resolved differently per parser."""
    raw = data.encode("utf-8", "surrogatepass") if isinstance(data, str) else data
    if len(raw) > max_bytes:
        raise ManifestError("wire_too_large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ManifestError("bad_encoding") from e

    def pairs(items):
        d: dict = {}
        for k, v in items:
            if k in d:
                raise ManifestError("duplicate_key")
            d[k] = v
        return d

    def bad_float(_s):
        raise ManifestError("float_not_allowed")

    def bad_const(_s):
        raise ManifestError("float_not_allowed")

    def parse_int(s):
        if s == "-0":
            raise ManifestError("negative_zero")
        if len(s) > 17:  # beyond +/-(2^53-1) anyway; never hand it to int()
            raise ManifestError("int_out_of_range")
        return int(s)

    try:
        obj = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_float=bad_float,
            parse_constant=bad_const,
            parse_int=parse_int,
        )
    except RecursionError as e:
        raise ManifestError("too_deep") from e
    except json.JSONDecodeError as e:
        raise ManifestError("bad_json") from e
    _check_json(obj)
    return obj


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


_B64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?")


def _b64decode(value: Any) -> bytes:
    """Canonical standard base64 only: right alphabet, right padding, no extra `=`, and no
    spare bits set, so one byte string has exactly one accepted spelling."""
    if not isinstance(value, str) or not _B64.fullmatch(value):
        raise ValueError("not canonical base64")
    raw = base64.b64decode(value)
    if base64.b64encode(raw).decode() != value:
        raise ValueError("not canonical base64")
    return raw


def key_id(public_b64: str) -> str:
    """Recomputed from the public key by every verifier; never taken on trust."""
    try:
        return hashlib.sha256(_b64decode(public_b64)).hexdigest()[:32]
    except (ValueError, TypeError) as e:
        raise ManifestError("bad_key") from e


def _verify_sig(public_b64: str, kind: str, payload: dict, sig_b64: str) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(_b64decode(public_b64)).verify(
            _b64decode(sig_b64), _signed_bytes(kind, payload)
        )
    except (InvalidSignature, ValueError, TypeError) as e:
        raise ManifestError("bad_signature") from e


def _sign(private_b64: str, kind: str, payload: dict) -> str:
    return base64.b64encode(
        load_private(private_b64).sign(_signed_bytes(kind, payload))
    ).decode()


def _only(d: Any, allowed: set[str], code: str = "malformed") -> dict:
    """Reject non-objects and unknown fields (a signed document has no free-form room)."""
    if not isinstance(d, dict) or set(d) - allowed:
        raise ManifestError(code)
    return d


# ── root-signed documents ────────────────────────────────────────────────────

_CERT_KEYS = {
    "typ",
    "v",
    "kid",
    "pub",
    "issuer_kid",
    "not_before",
    "not_after",
    "serial",
    "epoch",
}
_CRL_KEYS = {"typ", "v", "number", "revoked_kids", "issued_at", "next_update"}


def issue_signing_cert(
    root_private_b64: str,
    signing_public_b64: str,
    *,
    not_before: int,
    not_after: int,
    serial: int,
    epoch: int = 1,
) -> dict:
    """Run offline with the root key. The server only ever receives the result.
    `epoch` is raised by the root to recover from a compromised signing key: a
    client that has seen epoch N refuses N-1, and restarts its generation floor at N."""
    if not _is_int(epoch) or epoch < 1:
        raise ManifestError("bad_epoch")
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
        "epoch": epoch,
    }
    return {"payload": payload, "sig": _sign(root_private_b64, "cert", payload)}


def issue_crl(
    root_private_b64: str,
    *,
    number: int,
    revoked_kids: list[str],
    issued_at: int,
    next_update: int,
) -> dict:
    """A CRL is a full cumulative snapshot of every revoked key id so far."""
    if not all(isinstance(k, str) and _KID.fullmatch(k) for k in revoked_kids):
        raise ManifestError("bad_kid")
    payload = {
        "typ": "fab-crl",
        "v": 1,
        "number": number,
        "revoked_kids": sorted(set(revoked_kids)),
        "issued_at": issued_at,
        "next_update": next_update,
    }
    return {"payload": payload, "sig": _sign(root_private_b64, "crl", payload)}


# ── manifest body validation ─────────────────────────────────────────────────

_BODY_KEYS = {
    "typ", "v", "epoch", "company_id", "person_id", "aud", "generation", "issued_at",
    "expires_at", "min_client_version", "gateway_url", "layout", "mods",
}  # fmt: skip


def _check_name(name: Any) -> str:
    if (
        not isinstance(name, str)
        or not _NAME.fullmatch(name)
        or name.endswith(".")
        or name.split(".")[0] in _RESERVED
    ):
        raise ManifestError("bad_name")
    return name


_PATH_PART = re.compile(r"[A-Za-z0-9._@+-]{1,255}")


def _safe_path(path: Any) -> str:
    """Portable path profile: ASCII letters, digits and `. _ @ + -` per component, no
    empty / `.` / `..` component, no trailing dot, no Windows device name. ASCII-only is
    deliberate: it makes normalisation and case-folding questions disappear, so the Python
    signer and every verifier (TypeScript included) agree on collisions without sharing
    Unicode tables."""
    if not isinstance(path, str) or not path or len(path) > 200 or path.startswith("/"):
        raise ManifestError("bad_path")
    for part in path.split("/"):
        if (
            part in ("", ".", "..")
            or not _PATH_PART.fullmatch(part)
            or part.endswith(".")
            or part.split(".")[0].lower() in _RESERVED
        ):
            raise ManifestError("bad_path")
    return path


def _check_https_url(url: Any) -> None:
    if (
        not isinstance(url, str)
        or len(url) > 300
        or any(c.isspace() or ord(c) < 0x20 for c in url)
    ):
        raise ManifestError("bad_gateway_url")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError as e:
        raise ManifestError("bad_gateway_url") from e
    if (
        u.scheme != "https"
        or not u.hostname
        or len(u.hostname) > 253
        or not all(_LABEL.fullmatch(lbl) for lbl in u.hostname.split("."))
        or u.username is not None
        or u.password is not None
        or u.fragment
        or (port is not None and not 0 < port < 65536)
    ):
        raise ManifestError("bad_gateway_url")


def _validate_body(p: dict) -> None:
    """Shape and limits of a manifest payload. Used when building and verifying."""
    _only(p, _BODY_KEYS)
    if not _is_int(p.get("epoch")) or p["epoch"] < 1:
        raise ManifestError("bad_epoch")
    for k in ("company_id", "person_id"):
        if not isinstance(p.get(k), str) or not _ID.fullmatch(p[k]):
            raise ManifestError("bad_binding")
    if not isinstance(p.get("aud"), str) or not _NAME.fullmatch(p["aud"]):
        raise ManifestError("bad_binding")
    if not _is_int(p.get("generation")) or p["generation"] < 1:
        raise ManifestError("bad_generation")
    for k in ("issued_at", "expires_at"):
        if not _is_int(p.get(k)) or p[k] < 0:
            raise ManifestError("bad_time")
    if not 0 < p["expires_at"] - p["issued_at"] <= MAX_MANIFEST_LIFETIME:
        raise ManifestError("bad_lifetime")
    if not isinstance(p.get("min_client_version"), str) or not _VERSION.fullmatch(
        p["min_client_version"]
    ):
        raise ManifestError("bad_version")
    _check_https_url(p.get("gateway_url"))

    layout = _only(p.get("layout"), {"id", "sha256", "size"}, "bad_layout")
    _check_name(layout.get("id"))
    if not isinstance(layout.get("sha256"), str) or not _SHA256.fullmatch(
        layout["sha256"]
    ):
        raise ManifestError("bad_layout")
    if not _is_int(layout.get("size")) or layout["size"] < 0:
        raise ManifestError("bad_size")
    total = layout["size"]

    mods = p.get("mods")
    if not isinstance(mods, list) or len(mods) > MAX_MODS:
        raise ManifestError("bad_mods")
    seen_mods: set[str] = set()
    for m in mods:
        _only(m, {"name", "version", "files"}, "bad_mod")
        name = _check_name(m.get("name"))
        if name in seen_mods:
            raise ManifestError("duplicate_mod")
        seen_mods.add(name)
        if not isinstance(m.get("version"), str) or not _VERSION.fullmatch(
            m["version"]
        ):
            raise ManifestError("bad_mod")
        files = m.get("files")
        if not isinstance(files, list) or not files or len(files) > MAX_FILES_PER_MOD:
            raise ManifestError("bad_mod_files")
        keys: set[str] = set()
        for f in files:
            _only(f, {"path", "sha256", "size"}, "bad_mod_files")
            path = _safe_path(f.get("path"))
            key = path.lower()
            if key in keys:
                raise ManifestError("duplicate_path")
            keys.add(key)
            if not isinstance(f.get("sha256"), str) or not _SHA256.fullmatch(
                f["sha256"]
            ):
                raise ManifestError("bad_hash")
            if not _is_int(f.get("size")) or f["size"] < 0:
                raise ManifestError("bad_size")
            total += f["size"]
        for key in keys:  # a file and a directory of the same name cannot coexist
            parts = key.split("/")
            if any("/".join(parts[:i]) in keys for i in range(1, len(parts))):
                raise ManifestError("path_conflict")
    if total > MAX_TOTAL_BYTES:
        raise ManifestError("too_large")


def sign_manifest(signing_private_b64: str, cert: dict, payload: dict) -> dict:
    """Server side. Refuses to sign a body that would not verify."""
    body = {
        "typ": "fab-workspace-manifest",
        "v": 1,
        "epoch": cert["payload"]["epoch"],
        **payload,
    }
    _validate_body(body)
    pub = base64.b64encode(_pub_raw(load_private(signing_private_b64))).decode()
    if cert["payload"]["kid"] != key_id(pub):
        raise ManifestError("cert_key_mismatch")
    return {
        "cert": cert,
        "payload": body,
        "sig": _sign(signing_private_b64, "manifest", body),
    }


# ── verification (client) ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Expected:
    """What the client already knows from its own session, never from the manifest.

    `min_generation`, `min_epoch` and `min_crl_number` are floors from an authenticated
    online bootstrap (the signed-in session asks the server for them). They are
    **required** whenever the client has no history for this person (empty state, or no
    entry for the person): the verifier raises `bootstrap_floor_required` rather than
    start from zero. A first-ever enrolment passes 1, 1 and 0. Floors come from the
    session, never from the manifest. The CRL floor is a checkpoint (a revocation list
    number), because a generation or epoch floor does not carry the revoked-key set."""

    company_id: str
    person_id: str
    aud: str  # e.g. "herdr-provisioner"
    client_version: str = "0.0.0"
    min_generation: int | None = None
    min_epoch: int | None = None
    min_crl_number: int | None = None


@dataclass(frozen=True)
class ClientState:
    """Persisted by the client (atomically, under a lock) after each accepted document."""

    generations: dict[str, dict[str, Any]] = field(default_factory=dict)
    epoch: int = 0
    crl_number: int = 0
    crl_digest: str = ""
    crl_next_update: int = 0
    revoked: frozenset[str] = frozenset()
    last_seen: int = 0  # highest clock reading accepted; the clock may not go back
    signing_kid: str = ""  # key that signed the last accepted manifest


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _binding_key(company_id: str, person_id: str) -> str:
    return json.dumps([company_id, person_id], separators=(",", ":"))  # unambiguous


def _check_clock(now: int, state: ClientState) -> ClientState:
    if not _is_int(now) or now < 0:
        raise ManifestError("bad_clock")
    if now + CLOCK_SKEW < state.last_seen:
        raise ManifestError("clock_rollback", state)
    return replace(state, last_seen=max(state.last_seen, now))


def verify_crl(
    crl: dict, root_pub_b64: str, state: ClientState, now: int
) -> ClientState:
    """Ingest a revocation list. Call this on its own and persist the result BEFORE
    verifying any manifest, so a revocation survives a rejected manifest."""
    _only(crl, {"payload", "sig"}, "bad_crl")
    p = _only(crl.get("payload"), _CRL_KEYS, "bad_crl")
    if p.get("typ") != "fab-crl" or not _v1(p.get("v")):
        raise ManifestError("bad_crl")
    _verify_sig(root_pub_b64, "crl", p, crl.get("sig", ""))
    kids = p.get("revoked_kids")
    if (
        not _is_int(p.get("number"))
        or p["number"] < 1
        or not _is_int(p.get("issued_at"))
        or not _is_int(p.get("next_update"))
        or p["next_update"] <= p["issued_at"]
        or not isinstance(kids, list)
        or len(kids) > MAX_CRL_ENTRIES
        or not all(isinstance(k, str) and _KID.fullmatch(k) for k in kids)
        or kids != sorted(set(kids))
    ):
        raise ManifestError("bad_crl")
    state = _check_clock(now, state)
    if p["issued_at"] > now + CLOCK_SKEW:
        raise ManifestError("crl_from_future", state)
    d = digest(p)
    if p["number"] < state.crl_number:
        raise ManifestError("crl_rollback", state)
    if p["number"] == state.crl_number:
        if d != state.crl_digest:
            raise ManifestError("crl_conflict", state)
        return state
    if not state.revoked <= set(kids):
        raise ManifestError("crl_not_cumulative", state)
    return replace(
        state,
        crl_number=p["number"],
        crl_digest=d,
        crl_next_update=p["next_update"],
        revoked=frozenset(kids),
    )


def verify_manifest(
    envelope: dict,
    *,
    root_pub_b64: str,
    expected: Expected,
    now: int,
    state: ClientState,
    crl: dict | None = None,
    require_crl: bool = False,
) -> tuple[dict, ClientState]:
    """
    Returns `(payload, new_state)` or raises ManifestError (its `.state` is the state
    reached so far). Order: clock, revocation list, certificate (root signature,
    recomputed key id, window, epoch), manifest signature, shape, bindings, time,
    floors, replay/rollback. Nothing is installed by this function.

    `require_crl=True` demands that a revocation list has been seen and is not past its
    `next_update`; without it, revocation reaches the client only as fast as it learns of
    a list, and the hard bound for a stolen signing key is the certificate's expiry.
    """
    try:
        state = _check_clock(now, state)
        if crl is not None:
            state = verify_crl(crl, root_pub_b64, state, now)
        return _verify(envelope, root_pub_b64, expected, now, state, require_crl)
    except ManifestError as e:
        if e.state is None:
            e.state = state
        raise


def check_certificate(cert: Any, root_pub_b64: str, now: int) -> dict:
    """Everything about a signing certificate that needs no client state: shape,
    root signature, issuer, recomputed key id, lifetime and the validity window.
    Returns the certificate payload. The server uses it to check its own certificate
    before signing; the verifier uses it first."""
    _only(cert, {"payload", "sig"}, "bad_cert")
    cp = _only(cert.get("payload"), _CERT_KEYS, "bad_cert")
    if cp.get("typ") != "fab-signing-cert" or not _v1(cp.get("v")):
        raise ManifestError("bad_cert")
    _verify_sig(root_pub_b64, "cert", cp, cert.get("sig", ""))
    if cp.get("issuer_kid") != key_id(root_pub_b64):
        raise ManifestError("bad_cert")
    if not isinstance(cp.get("pub"), str) or cp.get("kid") != key_id(cp["pub"]):
        raise ManifestError("bad_cert")
    nb, na, epoch = cp.get("not_before"), cp.get("not_after"), cp.get("epoch")
    if not (
        _is_int(nb) and _is_int(na) and _is_int(epoch) and _is_int(cp.get("serial"))
    ):
        raise ManifestError("bad_cert")
    if not 0 < na - nb <= MAX_CERT_LIFETIME or epoch < 1:
        raise ManifestError("bad_cert")
    if now + CLOCK_SKEW < nb or now - CLOCK_SKEW > na:
        raise ManifestError("cert_not_valid_now")
    return cp


def _verify(
    envelope: dict,
    root_pub_b64: str,
    expected: Expected,
    now: int,
    state: ClientState,
    require_crl: bool,
) -> tuple[dict, ClientState]:
    if not isinstance(expected.client_version, str) or not _VERSION.fullmatch(
        expected.client_version
    ):  # a malformed trusted value must not make the version check pass or crash
        raise ManifestError("bad_client_version")
    _only(envelope, {"cert", "payload", "sig"})
    cert, payload = envelope.get("cert"), envelope.get("payload")
    if not isinstance(payload, dict):
        raise ManifestError("malformed")
    cp = check_certificate(cert, root_pub_b64, now)
    epoch = cp["epoch"]
    if cp["kid"] in state.revoked:
        raise ManifestError("cert_revoked")
    if require_crl:
        if state.crl_number < 1:
            raise ManifestError("crl_required")
        if now - CLOCK_SKEW > state.crl_next_update:
            raise ManifestError("crl_stale")
    if epoch < state.epoch:
        raise ManifestError("epoch_rollback")
    if epoch > state.epoch and state.signing_kid and cp["kid"] == state.signing_kid:
        # Raising the epoch is recovery from a stolen key; re-certifying the same
        # key would hand the thief a fresh start. Recovery needs a new signing key.
        raise ManifestError("epoch_needs_new_key")

    if payload.get("typ") != "fab-workspace-manifest" or not _v1(payload.get("v")):
        raise ManifestError("malformed")
    _verify_sig(cp["pub"], "manifest", payload, envelope.get("sig", ""))
    _validate_body(payload)
    if (
        payload["epoch"] != epoch
    ):  # the signed manifest is bound to its certificate's epoch
        raise ManifestError("epoch_mismatch")

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
    if (
        payload["issued_at"] < cp["not_before"]
        or payload["expires_at"] > cp["not_after"]
    ):
        raise ManifestError("outside_cert_window")

    key = _binding_key(payload["company_id"], payload["person_id"])
    if state.epoch == 0 or key not in state.generations:
        # No history for this person: never start from zero on the caller's say-so.
        if None in (
            expected.min_generation,
            expected.min_epoch,
            expected.min_crl_number,
        ):
            raise ManifestError("bootstrap_floor_required")
    if expected.min_epoch is not None and epoch < expected.min_epoch:
        raise ManifestError("epoch_rollback")
    if (
        expected.min_generation is not None
        and payload["generation"] < expected.min_generation
    ):
        raise ManifestError("below_floor")
    if (
        expected.min_crl_number is not None
        and state.crl_number < expected.min_crl_number
    ):
        raise ManifestError("crl_below_floor")

    gens = state.generations
    if epoch > state.epoch:  # root-authorised recovery: the generation floor restarts
        gens = {}
    d = digest(payload)
    last = gens.get(key)
    if last:
        if payload["generation"] < last["generation"]:
            raise ManifestError("rollback")
        if payload["generation"] == last["generation"] and d != last["digest"]:
            raise ManifestError("generation_conflict")
    gens = {**gens, key: {"generation": payload["generation"], "digest": d}}
    return payload, replace(
        state, generations=gens, epoch=max(epoch, state.epoch), signing_kid=cp["kid"]
    )


def verify_wire(data: bytes | str, **kwargs: Any) -> tuple[dict, ClientState]:
    """`verify_manifest` for untrusted bytes: strict parse first."""
    return verify_manifest(parse_wire(data), **kwargs)


def verify_file(content: bytes, entry: dict) -> None:
    """The provisioner calls this for each downloaded file before staging it."""
    if len(content) != entry["size"]:
        raise ManifestError("size_mismatch")
    if hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise ManifestError("hash_mismatch")
