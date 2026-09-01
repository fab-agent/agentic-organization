"""
Persona tokens for the workstation LLM gateway (ADR-0004, ADR-0007).

Separate from the web session JWT (`services.auth`): these are short-lived,
persona-scoped bearer tokens carried by the workstation agent (`3pa` → opencode)
when it calls `/v1/*` and `/audit/ingest`.

Faz 0: minted by a manager via `POST /gateway/persona-token`, HS256, `aud`-scoped.
Faz 2 (ADR-0007): issued through `3pa login` against an IdP, with silent refresh
and a server-side revocation list.
"""

import os
from datetime import datetime, timedelta

from jose import jwt

_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-please")
_ALG = "HS256"

# Short by design — a leaked token should die fast (ADR-0007).
PERSONA_TOKEN_TTL_MINUTES = int(os.getenv("PERSONA_TOKEN_TTL_MINUTES", "60"))

AUD_GATEWAY = "gateway"
AUD_AUDIT = "audit"


class PersonaPrincipal:
    """Decoded identity of a workstation agent acting as one persona."""

    def __init__(self, persona_id: str, company_id: str, scope: str | None):
        self.persona_id = persona_id
        self.company_id = company_id
        self.scope = scope


def create_persona_token(
    persona_id: str,
    company_id: str,
    scope: str | None = None,
    audience: str | list[str] | None = None,
    ttl_minutes: int | None = None,
) -> str:
    # One token serves both the LLM gateway and the audit ingest surface.
    if audience is None:
        audience = [AUD_GATEWAY, AUD_AUDIT]
    ttl = PERSONA_TOKEN_TTL_MINUTES if ttl_minutes is None else ttl_minutes
    now = datetime.utcnow()
    payload = {
        "sub": persona_id,
        "company_id": company_id,
        "scope": scope,
        "aud": audience,
        "typ": "persona",
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


def decode_persona_token(token: str, expected_audience: str) -> PersonaPrincipal:
    """Returns a PersonaPrincipal or raises jose.JWTError."""
    payload = jwt.decode(token, _SECRET, algorithms=[_ALG], audience=expected_audience)
    if payload.get("typ") != "persona":
        raise ValueError("not a persona token")
    return PersonaPrincipal(
        persona_id=payload["sub"],
        company_id=payload["company_id"],
        scope=payload.get("scope"),
    )
