"""
Pluggable OIDC (ADR-0007).

Platform-local identity (email + password via /auth/token) is the baseline and
always works. An organisation that runs its own IdP can additionally enable OIDC:
`3pa login --oidc` runs a standard OIDC flow client-side and posts the resulting
ID token to `POST /workstation/oidc/exchange`, which verifies it here and, if the
`email` claim maps to an existing platform `User`, returns a normal web session
token. Persona selection is unchanged from there.

Config (AppConfig keys, set by an admin):
  oidc.enabled     "true" to accept exchanges
  oidc.issuer      e.g. https://login.example.com   (required)
  oidc.client_id   the audience to require           (required)
  oidc.jwks_uri    optional; otherwise discovered from the issuer

No auto-provisioning: a token for an unknown email is rejected, not turned into
a new account.
"""

from __future__ import annotations

import time

import httpx
from jose import jwt

_DISCOVERY_TTL = 3600
_JWKS_TTL = 3600
_cache: dict[str, tuple[float, object]] = {}


class OIDCError(Exception):
    pass


def _cfg(key: str) -> str | None:
    try:
        from database import get_session
        from models import AppConfig

        with get_session() as session:
            row = session.get(AppConfig, key)
            return row.value if row and row.value else None
    except Exception:
        return None


def is_enabled() -> bool:
    return (_cfg("oidc.enabled") or "").lower() == "true"


def _get_cached(key: str, ttl: float, loader):
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    value = loader()
    _cache[key] = (time.time(), value)
    return value


def _discover(issuer: str) -> dict:
    def _load():
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        with httpx.Client(timeout=10) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.json()

    return _get_cached(f"disc:{issuer}", _DISCOVERY_TTL, _load)


def _jwks(jwks_uri: str) -> dict:
    def _load():
        with httpx.Client(timeout=10) as c:
            r = c.get(jwks_uri)
            r.raise_for_status()
            return r.json()

    return _get_cached(f"jwks:{jwks_uri}", _JWKS_TTL, _load)


def verify_id_token(id_token: str) -> dict:
    """Verify signature + iss + aud + exp against the configured IdP. Returns claims."""
    if not is_enabled():
        raise OIDCError("OIDC is not enabled")
    issuer = _cfg("oidc.issuer")
    client_id = _cfg("oidc.client_id")
    if not issuer or not client_id:
        raise OIDCError("OIDC issuer / client_id not configured")

    jwks_uri = _cfg("oidc.jwks_uri")
    if not jwks_uri:
        try:
            jwks_uri = _discover(issuer)["jwks_uri"]
        except Exception as e:
            raise OIDCError(f"OIDC discovery failed: {e}") from e

    try:
        header = jwt.get_unverified_header(id_token)
    except Exception as e:
        raise OIDCError(f"malformed token: {e}") from e

    keys = _jwks(jwks_uri).get("keys", [])
    key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if key is None:
        # kid rotated — bust the cache once and retry
        _cache.pop(f"jwks:{jwks_uri}", None)
        keys = _jwks(jwks_uri).get("keys", [])
        key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise OIDCError("no matching JWKS key")

    try:
        return jwt.decode(
            id_token,
            key,
            algorithms=[header.get("alg", "RS256")],
            audience=client_id,
            issuer=issuer,
        )
    except Exception as e:
        raise OIDCError(f"token verification failed: {e}") from e
