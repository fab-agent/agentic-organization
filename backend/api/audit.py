"""Audit log API — read-only; company-wide founder/executive of that company."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import AuditLog, User
from services import authz

router = APIRouter(prefix="/audit", tags=["audit"])


def log_action(
    session,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    entity_name: str | None = None,
    company_id: str | None = None,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Helper called from other routers to record an audit event."""
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        company_id=company_id,
        user_id=user_id,
        details_json=json.dumps(details) if details else None,
        created_at=datetime.utcnow(),
    )
    session.add(entry)


@router.get("")
def list_audit_logs(
    company_id: str,
    entity_type: str | None = None,
    action: str | None = None,
    user_id: str | None = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        # The audit log is final-approver reading (404 for outsiders), per company.
        authz.require_role(session, user.id, company_id, authz.FINAL, company_wide=True)
        q = (
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(max(1, min(limit, 500)))
            .where(AuditLog.company_id == company_id)
        )
        if entity_type:
            q = q.where(AuditLog.entity_type == entity_type)
        if action:
            q = q.where(AuditLog.action == action)
        if user_id:
            q = q.where(AuditLog.user_id == user_id)
        rows = session.exec(q).all()
        return [
            {
                "id": r.id,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "entity_name": r.entity_name,
                "company_id": r.company_id,
                "user_id": r.user_id,
                "details": json.loads(r.details_json) if r.details_json else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
