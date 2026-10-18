"""Learned harness artifacts (ADR-0022 §2): read and roll back.

Creating one is only possible through an approved change request of type `harness`
(`api/change_requests.py`); there is no direct write here. Reading is for the
managers of the target; rolling back is final-approver work.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.audit import log_action
from api.auth import get_current_user
from database import get_session
from models import Department, HarnessArtifact, Personnel, User
from services import authz
from services import harness as svc

router = APIRouter(prefix="/harness", tags=["harness"])

_MAX = 200


def _dict(a: HarnessArtifact, with_content: bool = True) -> dict:
    d = {
        "id": a.id,
        "company_id": a.company_id,
        "level": a.level,
        "target_id": a.target_id,
        "kind": a.kind,
        "key": a.key,
        "version": a.version,
        "base_version": a.base_version,
        "content_hash": a.content_hash,
        "status": a.status,
        "source_cr_id": a.source_cr_id,
        "created_at": a.created_at.isoformat(),
    }
    if with_content:
        d["content"] = a.content
    return d


def _may_read(session, user: User, a: HarnessArtifact) -> bool:
    """Managers of the artifact's target: company-wide for company level, the
    department's managers for department level, the person's managers for person level."""
    if a.level == "company":
        return authz.has_role(
            session, user.id, a.company_id, authz.MANAGERS, company_wide=True
        )
    if a.level == "department":
        d = session.get(Department, a.target_id)
        return bool(
            d
            and d.company_id == a.company_id
            and authz.has_role(
                session, user.id, a.company_id, authz.MANAGERS, department_id=d.id
            )
        )
    p = session.get(Personnel, a.target_id)
    return bool(
        p
        and p.company_id == a.company_id
        and authz.is_member(session, user.id, a.company_id)
        and authz.can_manage_agent(session, user.id, p)
    )


@router.get("")
def list_artifacts(
    company_id: str,
    level: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        authz.require_member(session, user.id, company_id)
        q = select(HarnessArtifact).where(HarnessArtifact.company_id == company_id)
        if level:
            q = q.where(HarnessArtifact.level == level)
        if target_id:
            q = q.where(HarnessArtifact.target_id == target_id)
        if status:
            q = q.where(HarnessArtifact.status == status)
        rows = session.exec(
            q.order_by(HarnessArtifact.created_at.desc()).limit(_MAX)
        ).all()
        return [_dict(a) for a in rows if _may_read(session, user, a)]


@router.get("/{artifact_id}")
def get_artifact(artifact_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        a = session.get(HarnessArtifact, artifact_id)
        if not a or not _may_read(session, user, a):
            raise HTTPException(status_code=404, detail="Not found")
        return _dict(a)


@router.post("/{artifact_id}/rollback", status_code=201)
def rollback_artifact(artifact_id: str, user: User = Depends(get_current_user)):
    """Restore the version before this (active) one as a new version."""
    with get_session() as session:
        a = session.get(HarnessArtifact, artifact_id)
        if not a or not authz.is_member(session, user.id, a.company_id):
            raise HTTPException(status_code=404, detail="Not found")
        authz.require_role(
            session, user.id, a.company_id, authz.FINAL, company_wide=True
        )
        restored = svc.rollback(session, a)
        log_action(
            session,
            "rollback",
            "harness",
            entity_id=restored.id,
            entity_name=f"{a.kind}:{a.key} v{a.version}->v{restored.version}",
            company_id=a.company_id,
            user_id=user.id,
        )
        session.commit()
        session.refresh(restored)
        return _dict(restored)
