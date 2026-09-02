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

from fastapi import APIRouter, Depends, HTTPException
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


@router.post("/workstation/persona-token", status_code=201)
def mint_persona_token(
    body: PersonaTokenRequest, user: User = Depends(get_current_user)
):
    """
    Mint a short-lived persona token for one of the caller's own agent personas.
    Replaces the manager-only `/gateway/persona-token` for the `3pa login` flow.
    """
    with get_session() as session:
        allowed = {p["personnel_id"] for p in _personas_for_user(session, user)}
        if body.personnel_id not in allowed:
            raise HTTPException(status_code=403, detail="Bu persona için yetkiniz yok")
        person = session.get(Personnel, body.personnel_id)
    token = create_persona_token(
        persona_id=person.id, company_id=person.company_id, scope=None
    )
    return {"token": token, "token_type": "bearer", "persona_id": person.id}


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
