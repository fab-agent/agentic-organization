"""Shared FastAPI dependencies for workstation-agent-facing endpoints."""

from fastapi import Header, HTTPException
from sqlmodel import select

from database import get_session
from models import AgentConfig, Personnel
from services.gateway_auth import PersonaPrincipal, decode_persona_token


def _persona_from_header(
    authorization: str | None, audience: str, *, require_active: bool = False
) -> PersonaPrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Persona token gerekli")
    token = authorization.split(" ", 1)[1]
    try:
        principal = decode_persona_token(token, expected_audience=audience)
    except Exception:
        raise HTTPException(status_code=401, detail="Geçersiz persona token")

    # Server-side revocation (ADR-0007): spent/blacklisted jti, or a token issued
    # before the persona's "revoke everything" marker.
    from services.persona_revocation import is_revoked

    if is_revoked(principal.jti, principal.persona_id, principal.issued_at):
        raise HTTPException(status_code=401, detail="Persona token iptal edilmiş")

    with get_session() as session:
        person = session.get(Personnel, principal.persona_id)
        if not person or person.company_id != principal.company_id:
            raise HTTPException(status_code=401, detail="Persona bulunamadı")
        if person.type != "agent":
            raise HTTPException(status_code=403, detail="Persona bir ajan değil")
        if require_active:
            # An already minted token stops working once the agent is not active.
            cfg = session.exec(
                select(AgentConfig).where(AgentConfig.personnel_id == person.id)
            ).first()
            if not cfg or cfg.status != "active":
                raise HTTPException(status_code=403, detail="Ajan etkin değil")
    return principal


def get_persona_gateway(authorization: str | None = Header(None)) -> PersonaPrincipal:
    """Persona principal for the LLM gateway surface (aud=gateway)."""
    from services.gateway_auth import AUD_GATEWAY

    return _persona_from_header(authorization, AUD_GATEWAY, require_active=True)


def get_persona_audit(authorization: str | None = Header(None)) -> PersonaPrincipal:
    """Persona principal for the audit/tool-event ingest surface (aud=audit)."""
    from services.gateway_auth import AUD_AUDIT

    return _persona_from_header(authorization, AUD_AUDIT)
