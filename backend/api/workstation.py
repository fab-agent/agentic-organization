"""
Workstation-agent-facing endpoints (ADR-0001, ADR-0006).

The opencode org plugin (`packages/agent-plugin`) posts here as the agent runs on
a developer's laptop:
  - `POST /workstation/tool-event` — one record per tool-call lifecycle event
    (before / after / permission-asked). Faz 0: audit only, no gating.

Auth: persona bearer token (aud includes `audit`), same token the plugin uses for
the gateway. Identity resolution is shared via `api.deps`.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_persona_audit
from database import get_session
from models import AuditLog
from services.gateway_auth import PersonaPrincipal

router = APIRouter(prefix="/workstation", tags=["workstation"])

_ARGS_PREVIEW_CHARS = 2000


class ToolEvent(BaseModel):
    # "before" | "after" | "permission_asked" (opencode plugin hook names, normalised)
    phase: str
    tool: str
    session_ref: str | None = None  # opencode session id, opaque to us
    args_preview: dict | str | None = None
    result_preview: str | None = None
    decision: str | None = None  # "allow" | "ask" | "deny" — set from Faz 1 (ADR-0005)
    error: str | None = None
    client_ts: str | None = None
    extra: dict = Field(default_factory=dict)


@router.post("/tool-event", status_code=202)
def ingest_tool_event(
    event: ToolEvent, principal: PersonaPrincipal = Depends(get_persona_audit)
):
    args_preview = event.args_preview
    if isinstance(args_preview, dict):
        args_preview = json.dumps(args_preview, ensure_ascii=False)
    if isinstance(args_preview, str):
        args_preview = args_preview[:_ARGS_PREVIEW_CHARS]

    details = {
        "phase": event.phase,
        "session_ref": event.session_ref,
        "args_preview": args_preview,
        "result_preview": (event.result_preview or "")[:_ARGS_PREVIEW_CHARS] or None,
        "decision": event.decision,
        "error": event.error,
        "client_ts": event.client_ts,
        **({"extra": event.extra} if event.extra else {}),
    }

    # TODO(ADR-0006): route through services.audit_chain for a hash-chained,
    # tamper-evident, append-only record instead of a plain AuditLog row.
    with get_session() as session:
        session.add(
            AuditLog(
                company_id=principal.company_id,
                user_id=None,
                action="tool_event",
                entity_type="persona",
                entity_id=principal.persona_id,
                entity_name=event.tool,
                details_json=json.dumps(details, ensure_ascii=False),
                created_at=datetime.utcnow(),
            )
        )
        session.commit()
    return {"accepted": True}
