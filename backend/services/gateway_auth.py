"""
Persona tokens for the workstation LLM gateway (ADR-0004, ADR-0007).

Separate from the web session JWT (`services.auth`): these are short-lived,
persona-scoped bearer tokens carried by the workstation agent (`3pa` → opencode)
when it calls `/v1/*` and `/audit/ingest`.

Two token types:
  - **access**  (`typ="persona"`, `aud=[gateway, audit]`) — short TTL, sent on
    every request. `PERSONA_TOKEN_TTL_MINUTES` (default 60).
  - **refresh** (`typ="persona_refresh"`, `aud="refresh"`) — longer TTL, only
    ever sent to `POST /workstation/persona-token/refresh`, which rotates it and
    mints a fresh access token. `PERSONA_REFRESH_TTL_HOURS` (default 12).

Every token carries a `jti`. Revocation (`services.persona_revocation`): a
spent/blacklisted `jti`, or an `iat` before the persona's `not_before` marker,
is rejected by the workstation auth deps even while the signature still checks.
"""

import os
import uuid
from datetime import datetime, timedelta

from jose import jwt

_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-please")
_ALG = "HS256"

# Short by design — a leaked access token should die fast (ADR-0007).
PERSONA_TOKEN_TTL_MINUTES = int(os.getenv("PERSONA_TOKEN_TTL_MINUTES", "60"))
PERSONA_REFRESH_TTL_HOURS = int(os.getenv("PERSONA_REFRESH_TTL_HOURS", "12"))

AUD_GATEWAY = "gateway"
AUD_AUDIT = "audit"
AUD_REFRESH = "refresh"

_TYP_ACCESS = "persona"
_TYP_REFRESH = "persona_refresh"


class PersonaPrincipal:
    """Decoded identity of a workstation agent acting as one persona."""

    def __init__(
        self,
        persona_id: str,
        company_id: str,
        scope: str | None,
        jti: str | None = None,
        issued_at: datetime | None = None,
    ):
        self.persona_id = persona_id
        self.company_id = company_id
        self.scope = scope
        self.jti = jti
        self.issued_at = issued_at


def _new_jti() -> str:
    return uuid.uuid4().hex


def create_persona_token(
    persona_id: str,
    company_id: str,
    scope: str | None = None,
    audience: str | list[str] | None = None,
    ttl_minutes: int | None = None,
    jti: str | None = None,
) -> str:
    """Mint an access token. One token serves both `/v1/*` and `/audit/ingest`."""
    if audience is None:
        audience = [AUD_GATEWAY, AUD_AUDIT]
    ttl = PERSONA_TOKEN_TTL_MINUTES if ttl_minutes is None else ttl_minutes
    now = datetime.utcnow()
    payload = {
        "sub": persona_id,
        "company_id": company_id,
        "scope": scope,
        "aud": audience,
        "typ": _TYP_ACCESS,
        "jti": jti or _new_jti(),
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


def create_persona_refresh_token(
    persona_id: str,
    company_id: str,
    scope: str | None = None,
    ttl_hours: int | None = None,
    jti: str | None = None,
) -> str:
    """Mint a refresh token — only accepted by the refresh endpoint."""
    ttl = PERSONA_REFRESH_TTL_HOURS if ttl_hours is None else ttl_hours
    now = datetime.utcnow()
    payload = {
        "sub": persona_id,
        "company_id": company_id,
        "scope": scope,
        "aud": AUD_REFRESH,
        "typ": _TYP_REFRESH,
        "jti": jti or _new_jti(),
        "iat": now,
        "exp": now + timedelta(hours=ttl),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


def _decode(token: str, expected_audience: str) -> dict:
    return jwt.decode(token, _SECRET, algorithms=[_ALG], audience=expected_audience)


def _issued_at(payload: dict) -> datetime | None:
    iat = payload.get("iat")
    if iat is None:
        return None
    return iat if isinstance(iat, datetime) else datetime.utcfromtimestamp(iat)


def decode_persona_token(token: str, expected_audience: str) -> PersonaPrincipal:
    """Decode an access token. Returns a PersonaPrincipal or raises."""
    payload = _decode(token, expected_audience)
    if payload.get("typ") != _TYP_ACCESS:
        raise ValueError("not a persona access token")
    return PersonaPrincipal(
        persona_id=payload["sub"],
        company_id=payload["company_id"],
        scope=payload.get("scope"),
        jti=payload.get("jti"),
        issued_at=_issued_at(payload),
    )


def decode_persona_refresh_token(token: str) -> PersonaPrincipal:
    """Decode a refresh token (aud=refresh). Returns a PersonaPrincipal or raises."""
    payload = _decode(token, AUD_REFRESH)
    if payload.get("typ") != _TYP_REFRESH:
        raise ValueError("not a persona refresh token")
    return PersonaPrincipal(
        persona_id=payload["sub"],
        company_id=payload["company_id"],
        scope=payload.get("scope"),
        jti=payload.get("jti"),
        issued_at=_issued_at(payload),
    )
