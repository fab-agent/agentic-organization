"""
Change Request API — two-stage approval flow ending in a GitHub commit.

Lifecycle:
  submitted → dept_head_approved → admin_approved → committed
           ↘ rejected (at any stage)
"""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.audit import log_action
from api.auth import get_current_user
from database import get_session
from models import ChangeRequest, GitConfig, Personnel, User
from schemas import ChangeRequestCreate, ChangeRequestApprove, ChangeRequestReject
from services.github_commit import commit_change_request

router = APIRouter(prefix="/change-requests", tags=["change-requests"])


def _cr_to_dict(cr: ChangeRequest) -> dict:
    return {
        "id": cr.id,
        "company_id": cr.company_id,
        "personnel_id": cr.personnel_id,
        "change_type": cr.change_type,
        "title": cr.title,
        "proposed": json.loads(cr.proposed_json),
        "original": json.loads(cr.original_json) if cr.original_json else None,
        "status": cr.status,
        "dept_head_id": cr.dept_head_id,
        "dept_head_approved_at": cr.dept_head_approved_at.isoformat() if cr.dept_head_approved_at else None,
        "dept_head_rejected_at": cr.dept_head_rejected_at.isoformat() if cr.dept_head_rejected_at else None,
        "dept_head_note": cr.dept_head_note,
        "admin_id": cr.admin_id,
        "admin_approved_at": cr.admin_approved_at.isoformat() if cr.admin_approved_at else None,
        "admin_rejected_at": cr.admin_rejected_at.isoformat() if cr.admin_rejected_at else None,
        "admin_note": cr.admin_note,
        "commit_sha": cr.commit_sha,
        "commit_url": cr.commit_url,
        "created_by_user_id": cr.created_by_user_id,
        "created_at": cr.created_at.isoformat(),
        "updated_at": cr.updated_at.isoformat(),
    }


# ── List & Get ────────────────────────────────────────────────────────────────

@router.get("")
def list_change_requests(
    company_id: Optional[str] = None,
    status: Optional[str] = None,
    personnel_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        q = select(ChangeRequest)
        if company_id:
            q = q.where(ChangeRequest.company_id == company_id)
        if status:
            q = q.where(ChangeRequest.status == status)
        if personnel_id:
            q = q.where(ChangeRequest.personnel_id == personnel_id)
        q = q.order_by(ChangeRequest.created_at.desc())
        return [_cr_to_dict(cr) for cr in session.exec(q).all()]


@router.get("/{cr_id}")
def get_change_request(cr_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        cr = session.get(ChangeRequest, cr_id)
        if not cr:
            raise HTTPException(status_code=404, detail="Change request not found")
        return _cr_to_dict(cr)


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_change_request(
    body: ChangeRequestCreate,
    company_id: str,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        personnel = session.get(Personnel, body.personnel_id)
        if not personnel:
            raise HTTPException(status_code=404, detail="Personnel not found")

        cr = ChangeRequest(
            company_id=company_id,
            personnel_id=body.personnel_id,
            change_type=body.change_type,
            title=body.title,
            proposed_json=json.dumps(body.proposed),
            original_json=json.dumps(body.original) if body.original else None,
            status="submitted",
            created_by_user_id=current_user.id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(cr)
        log_action(session, "create", "change_request", entity_id=cr.id, entity_name=cr.title, company_id=cr.company_id, user_id=current_user.id)
        session.commit()
        session.refresh(cr)
        return _cr_to_dict(cr)


# ── Stage 1: Dept Head Approval ───────────────────────────────────────────────

@router.post("/{cr_id}/dept-approve")
def dept_head_approve(
    cr_id: str,
    body: ChangeRequestApprove,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        cr = session.get(ChangeRequest, cr_id)
        if not cr:
            raise HTTPException(status_code=404, detail="Not found")
        if cr.status != "submitted":
            raise HTTPException(status_code=400, detail=f"CR is in '{cr.status}' status, expected 'submitted'")

        cr.status = "dept_head_approved"
        cr.dept_head_id = current_user.id
        cr.dept_head_approved_at = datetime.utcnow()
        cr.dept_head_note = body.note
        cr.updated_at = datetime.utcnow()
        session.add(cr)
        log_action(session, "approve", "change_request", entity_id=cr.id, entity_name=cr.title, company_id=cr.company_id, user_id=current_user.id, details={"stage": "dept_head"})
        session.commit()
        session.refresh(cr)
        return _cr_to_dict(cr)


@router.post("/{cr_id}/dept-reject")
def dept_head_reject(
    cr_id: str,
    body: ChangeRequestReject,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        cr = session.get(ChangeRequest, cr_id)
        if not cr:
            raise HTTPException(status_code=404, detail="Not found")
        if cr.status != "submitted":
            raise HTTPException(status_code=400, detail=f"CR is in '{cr.status}' status")

        cr.status = "rejected"
        cr.dept_head_id = current_user.id
        cr.dept_head_rejected_at = datetime.utcnow()
        cr.dept_head_note = body.note
        cr.updated_at = datetime.utcnow()
        session.add(cr)
        log_action(session, "reject", "change_request", entity_id=cr.id, entity_name=cr.title, company_id=cr.company_id, user_id=current_user.id, details={"stage": "dept_head"})
        session.commit()
        session.refresh(cr)
        return _cr_to_dict(cr)


# ── Stage 2: Admin Approval → GitHub Commit ───────────────────────────────────

@router.post("/{cr_id}/admin-approve")
def admin_approve(
    cr_id: str,
    body: ChangeRequestApprove,
    company_id: str,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        cr = session.get(ChangeRequest, cr_id)
        if not cr:
            raise HTTPException(status_code=404, detail="Not found")
        if cr.status != "dept_head_approved":
            raise HTTPException(status_code=400, detail=f"CR is in '{cr.status}' status, expected 'dept_head_approved'")

        # Mark admin approval
        cr.status = "admin_approved"
        cr.admin_id = current_user.id
        cr.admin_approved_at = datetime.utcnow()
        cr.admin_note = body.note
        cr.updated_at = datetime.utcnow()

        # Look up git config for this company
        git_cfg = session.exec(
            select(GitConfig).where(GitConfig.company_id == company_id)
        ).first()

        if git_cfg:
            try:
                sha, url = commit_change_request(session, cr, git_cfg, committer_name=current_user.name, committer_email=current_user.email)
                cr.commit_sha = sha
                cr.commit_url = url
                cr.status = "committed"
            except Exception as e:
                # Approval still saved, but commit failed — surface error
                cr.admin_note = f"{body.note or ''}\n[COMMIT ERROR: {str(e)}]".strip()
        else:
            # No git config — approval saved but no commit
            cr.status = "committed"  # treat as done, no repo configured

        cr.updated_at = datetime.utcnow()
        session.add(cr)
        log_action(session, "approve", "change_request", entity_id=cr.id, entity_name=cr.title, company_id=cr.company_id, user_id=current_user.id, details={"stage": "admin", "commit_sha": cr.commit_sha})
        session.commit()
        session.refresh(cr)
        return _cr_to_dict(cr)


@router.post("/{cr_id}/admin-reject")
def admin_reject(
    cr_id: str,
    body: ChangeRequestReject,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        cr = session.get(ChangeRequest, cr_id)
        if not cr:
            raise HTTPException(status_code=404, detail="Not found")
        if cr.status != "dept_head_approved":
            raise HTTPException(status_code=400, detail=f"CR is in '{cr.status}' status")

        cr.status = "rejected"
        cr.admin_id = current_user.id
        cr.admin_rejected_at = datetime.utcnow()
        cr.admin_note = body.note
        cr.updated_at = datetime.utcnow()
        session.add(cr)
        log_action(session, "reject", "change_request", entity_id=cr.id, entity_name=cr.title, company_id=cr.company_id, user_id=current_user.id, details={"stage": "admin"})
        session.commit()
        session.refresh(cr)
        return _cr_to_dict(cr)
