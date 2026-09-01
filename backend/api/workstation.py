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

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import require_manager
from api.deps import get_persona_audit
from models import User
from services import audit_chain
from services.gateway_auth import PersonaPrincipal

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


@router.get("/audit/chain/verify")
def verify_chain(company_id: str | None = None, _: User = Depends(require_manager)):
    """
    Verify the tamper-evident audit chain(s) and report the first break, if any.
    With `company_id` → just that tenant's chain; without → every chain.
    """
    if company_id:
        return audit_chain.verify(company_id)
    return audit_chain.verify_all()
