"""
Workstation-agent-facing endpoints (ADR-0001, ADR-0006).

The opencode org plugin (`packages/agent-plugin`) posts here as the agent runs on
a developer's laptop:
  - `POST /workstation/tool-event` — one record per tool-call lifecycle event
    (before / after / permission-asked).
  - `POST /audit/ingest` — a one-way batch feed into the tamper-evident chain.

Both write to `services.audit_chain` (hash-chained, append-only). `tool-event`
also mirrors a legacy `AuditLog` row for the existing `/audit` UI.

Auth: persona bearer token (aud includes `audit`), the same token the plugin uses
for the gateway. Identity resolution is shared via `api.deps`.
"""

import json

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from api.auth import get_current_user, require_manager
from api.deps import get_persona_audit
from database import get_session
from models import AgentConfig, CompanyMember, Personnel, User
from services import audit_chain
from services.auth import create_access_token
from services.gateway_auth import PersonaPrincipal, create_persona_token

router = APIRouter(tags=["workstation"])

_PREVIEW_CHARS = 2000


class ToolEvent(BaseModel):
    # "before" | "after" | "permission_asked" (opencode plugin hook names, normalised)
    phase: str
    tool: str
    session_ref: str | None = None  # opencode session id, opaque to us
    args_preview: dict | str | None = None
    result_preview: str | None = None
    decision: str | None = None  # "allow" | "ask" | "deny" (ADR-0005)
    provenance: str | None = None  # "trusted" | "untrusted" (ADR-0010)
    error: str | None = None
    client_ts: str | None = None
    extra: dict = Field(default_factory=dict)


@router.post("/workstation/tool-event", status_code=202)
def ingest_tool_event(
    event: ToolEvent, principal: PersonaPrincipal = Depends(get_persona_audit)
):
    args_preview = event.args_preview
    if isinstance(args_preview, dict):
        args_preview = json.dumps(args_preview, ensure_ascii=False)
    if isinstance(args_preview, str):
        args_preview = args_preview[:_PREVIEW_CHARS]

    payload = {
        "phase": event.phase,
        "session_ref": event.session_ref,
        "args_preview": args_preview,
        "result_preview": (event.result_preview or "")[:_PREVIEW_CHARS] or None,
        "decision": event.decision,
        "provenance": event.provenance,
        "error": event.error,
        "client_ts": event.client_ts,
        **({"extra": event.extra} if event.extra else {}),
    }
    audit_chain.record(
        actor_type="agent",
        actor_id=principal.persona_id,
        company_id=principal.company_id,
        action="tool_event",
        target=event.tool,
        reason=event.phase,
        payload=payload,
    )
    return {"accepted": True}


class AuditBatch(BaseModel):
    events: list[dict] = Field(default_factory=list)


@router.post("/audit/ingest", status_code=202)
def ingest_audit_batch(
    batch: AuditBatch, principal: PersonaPrincipal = Depends(get_persona_audit)
):
    """One-way feed from the workstation into the tamper-evident chain (ADR-0006)."""
    n = audit_chain.ingest_batch(
        batch.events,
        actor_id=principal.persona_id,
        company_id=principal.company_id,
    )
    return {"accepted": n}


# ── 3pa login: persona selection + token (ADR-0007) ─────────────────────────


def _personas_for_user(session, user: User) -> list[dict]:
    """
    Agent personas this user may act as: every agent in a company where they are
    founder/executive, plus any agent they are the responsible human for or own
    (CompanyMember role=agent_owner, scope_id=agent personnel id).
    """
    out: dict[str, dict] = {}
    memberships = session.exec(
        select(CompanyMember).where(CompanyMember.user_id == user.id)
    ).all()
    for m in memberships:
        my_person = session.exec(
            select(Personnel).where(
                Personnel.user_id == user.id,
                Personnel.company_id == m.company_id,
            )
        ).first()
        agents = session.exec(
            select(Personnel, AgentConfig)
            .join(AgentConfig, AgentConfig.personnel_id == Personnel.id)
            .where(Personnel.company_id == m.company_id)
            .where(Personnel.type == "agent")
        ).all()
        for person, cfg in agents:
            allowed = m.role in ("founder", "executive")
            if my_person and cfg.responsible_id == my_person.id:
                allowed = True
            if m.role == "agent_owner" and m.scope_id == person.id:
                allowed = True
            if allowed:
                out[person.id] = {
                    "personnel_id": person.id,
                    "name": person.name,
                    "slug": person.slug,
                    "title": person.title,
                    "company_id": person.company_id,
                    "department_id": person.department_id,
                    "model": cfg.model,
                }
    return list(out.values())


@router.get("/workstation/personas")
def list_personas(user: User = Depends(get_current_user)):
    """Agent personas the caller may run opencode as (`3pa login`)."""
    with get_session() as session:
        return {"personas": _personas_for_user(session, user)}


class PersonaTokenRequest(BaseModel):
    personnel_id: str


def _issue_token_pair(persona_id: str, company_id: str) -> dict:
    """A fresh access + refresh token pair for one persona (ADR-0007)."""
    from services.gateway_auth import (
        PERSONA_TOKEN_TTL_MINUTES,
        create_persona_refresh_token,
    )

    return {
        "token": create_persona_token(persona_id=persona_id, company_id=company_id),
        "refresh_token": create_persona_refresh_token(
            persona_id=persona_id, company_id=company_id
        ),
        "token_type": "bearer",
        "persona_id": persona_id,
        "expires_in": PERSONA_TOKEN_TTL_MINUTES * 60,
    }


@router.post("/workstation/persona-token", status_code=201)
def mint_persona_token(
    body: PersonaTokenRequest, user: User = Depends(get_current_user)
):
    """
    Mint a persona access + refresh token for one of the caller's own agent
    personas. Replaces the manager-only `/gateway/persona-token` for `3pa login`.
    """
    with get_session() as session:
        allowed = {p["personnel_id"] for p in _personas_for_user(session, user)}
        if body.personnel_id not in allowed:
            raise HTTPException(status_code=403, detail="Bu persona için yetkiniz yok")
        person = session.get(Personnel, body.personnel_id)
    return _issue_token_pair(person.id, person.company_id)


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/workstation/persona-token/refresh", status_code=201)
def refresh_persona_token(body: RefreshRequest):
    """
    Exchange a valid refresh token for a fresh access + refresh pair (ADR-0007).
    The presented refresh token is rotated — its `jti` is revoked, so it cannot
    be replayed. Auth is the refresh token itself; no web session needed.
    """
    from services.gateway_auth import decode_persona_refresh_token
    from services.persona_revocation import is_revoked, revoke_jti

    try:
        principal = decode_persona_refresh_token(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Geçersiz refresh token")

    if is_revoked(principal.jti, principal.persona_id, principal.issued_at):
        raise HTTPException(status_code=401, detail="Refresh token iptal edilmiş")

    with get_session() as session:
        person = session.get(Personnel, principal.persona_id)
        if not person or person.type != "agent":
            raise HTTPException(status_code=401, detail="Persona bulunamadı")

    if principal.jti:
        revoke_jti(principal.jti, principal.persona_id, principal.company_id, "rotated")
    return _issue_token_pair(person.id, person.company_id)


class RevokeRequest(BaseModel):
    personnel_id: str


@router.post("/workstation/persona-token/revoke", status_code=202)
def revoke_persona_tokens(
    body: RevokeRequest,
    authorization: str | None = Header(None),
):
    """
    Revoke **every** persona token (access + refresh) for one agent persona — the
    "laptop lost" button (ADR-0007). A subsequent `3pa login` mints a fresh token
    that is unaffected.

    Auth: either the platform owner of the persona (web session), or a still-valid
    persona token for that same persona (a laptop revoking itself, e.g.
    `3pa logout --revoke`).
    """
    from services.persona_revocation import revoke_all

    actor = _revoke_authorised(authorization, body.personnel_id)

    with get_session() as session:
        person = session.get(Personnel, body.personnel_id)
        if not person:
            raise HTTPException(status_code=404, detail="Persona bulunamadı")
        company_id = person.company_id

    not_before = revoke_all(body.personnel_id, company_id, f"revoked by {actor}")
    return {
        "revoked": True,
        "persona_id": body.personnel_id,
        "not_before": not_before.isoformat(),
    }


def _revoke_authorised(authorization: str | None, personnel_id: str) -> str:
    """Return an actor label, or raise 401/403. Owner web session OR self-token."""
    from services.auth import decode_token
    from services.gateway_auth import AUD_GATEWAY, decode_persona_token

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yetkilendirme gerekli")
    token = authorization.split(" ", 1)[1]

    # 1. A persona token that IS this persona (self-revoke).
    try:
        principal = decode_persona_token(token, expected_audience=AUD_GATEWAY)
        if principal.persona_id == personnel_id:
            return f"persona:{personnel_id}"
        raise HTTPException(status_code=403, detail="Başka persona iptal edilemez")
    except HTTPException:
        raise
    except Exception:
        pass

    # 2. A web session for a user who owns this persona.
    try:
        user_id = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Geçersiz token")
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")
        allowed = {p["personnel_id"] for p in _personas_for_user(session, user)}
    if personnel_id not in allowed:
        raise HTTPException(status_code=403, detail="Bu persona için yetkiniz yok")
    return f"user:{user_id}"


class OIDCExchange(BaseModel):
    id_token: str


@router.post("/workstation/oidc/exchange")
def oidc_exchange(body: OIDCExchange):
    """
    Verify an OIDC ID token from the org's IdP and, if its `email` maps to an
    existing platform user, return a normal web session token (ADR-0007). No
    auto-provisioning.
    """
    from services.oidc import OIDCError, verify_id_token

    try:
        claims = verify_id_token(body.id_token)
    except OIDCError as e:
        raise HTTPException(status_code=401, detail=f"OIDC: {e}")

    email = (claims.get("email") or "").strip().lower()
    if not email or not claims.get("email_verified", True):
        raise HTTPException(status_code=401, detail="OIDC: unusable email claim")

    with get_session() as session:
        u = session.exec(select(User).where(User.email == email)).first()
        if not u or not u.is_active:
            raise HTTPException(
                status_code=403, detail="No active platform user for this identity"
            )
        user_id = u.id

    return {
        "access_token": create_access_token(user_id),
        "token_type": "bearer",
        "user_id": user_id,
    }


@router.get("/audit/chain/verify")
def verify_chain(company_id: str | None = None, _: User = Depends(require_manager)):
    """
    Verify the tamper-evident audit chain(s) and report the first break, if any.
    With `company_id` → just that tenant's chain; without → every chain.
    """
    if company_id:
        return audit_chain.verify(company_id)
    return audit_chain.verify_all()
