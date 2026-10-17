"""
Change Request API — two-stage approval flow ending in a GitHub commit.

Lifecycle:
  submitted → dept_head_approved → admin_approved → committed
           ↘ rejected (at any stage)
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, update

from api.audit import log_action
from api.auth import check_company_membership, get_current_user
from database import get_session
from models import (
    AgentConfig,
    ChangeRequest,
    CompanyMember,
    Department,
    GitConfig,
    Personnel,
    Skill,
    User,
)
from schemas import ChangeRequestApprove, ChangeRequestCreate, ChangeRequestReject
from services.github_commit import commit_change_request

router = APIRouter(prefix="/change-requests", tags=["change-requests"])

# Who may decide at each stage. `scope_id` on a membership is the department the
# role manages (None = the whole company, see CompanyMember).
STAGE1_ROLES = {"founder", "executive", "dept_head"}
STAGE2_ROLES = {"founder", "executive"}


def _memberships(session, user_id: str, company_id: str) -> list[CompanyMember]:
    return list(
        session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user_id,
                CompanyMember.company_id == company_id,
            )
        ).all()
    )


def _claim(session, cr: ChangeRequest, expected: str, new: str) -> None:
    """Compare-and-swap the status inside the open transaction.

    Two concurrent decisions on one request cannot both win: the loser's UPDATE
    matches no row (it waits for the winner's row lock on PostgreSQL) and gets 409,
    before any side effect such as the Git commit.
    """
    res = session.exec(
        update(ChangeRequest)
        .where(ChangeRequest.id == cr.id, ChangeRequest.status == expected)
        .values(status=new)
    )
    if res.rowcount != 1:
        raise HTTPException(status_code=409, detail="Change request changed state")
    session.refresh(cr)


def _validate_proposed(session, company_id: str, proposed: dict) -> None:
    """Relations named in a proposal must belong to the request's own company."""
    dept_id = proposed.get("department_id")
    if dept_id is not None:
        dept = session.get(Department, dept_id)
        if not dept or dept.company_id != company_id:
            raise HTTPException(status_code=422, detail="Unknown department")
    resp_id = proposed.get("responsible_id")
    if resp_id is not None:
        resp = session.get(Personnel, resp_id)
        if not resp or resp.company_id != company_id:
            raise HTTPException(status_code=422, detail="Unknown responsible person")


def _require_stage1(session, user: User, cr: ChangeRequest) -> None:
    """Department-level approver of the target's department, not the proposer."""
    target = session.get(Personnel, cr.personnel_id)
    if not target or target.company_id != cr.company_id:
        # A vanished or moved target must not fall through to an unscoped approver.
        raise HTTPException(status_code=409, detail="Change request target is gone")
    dept = target.department_id
    allowed = any(
        m.role in STAGE1_ROLES and (m.scope_id is None or m.scope_id == dept)
        for m in _memberships(session, user.id, cr.company_id)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Department approval not permitted")
    if user.id == cr.created_by_user_id:
        raise HTTPException(
            status_code=403, detail="Proposer cannot approve own request"
        )


def _require_stage2(session, user: User, cr: ChangeRequest) -> None:
    """Company-level approver, different from the proposer and the stage-1 approver."""
    allowed = any(
        m.role in STAGE2_ROLES and m.scope_id is None
        for m in _memberships(session, user.id, cr.company_id)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Company approval not permitted")
    if user.id in (cr.created_by_user_id, cr.dept_head_id):
        raise HTTPException(
            status_code=403, detail="Approvers must differ from proposer and each other"
        )


def _get_visible_cr(session, user: User, cr_id: str) -> ChangeRequest:
    """404 for unknown *and* for other companies' requests (no enumeration)."""
    cr = session.get(ChangeRequest, cr_id)
    if not cr or not _memberships(session, user.id, cr.company_id):
        raise HTTPException(status_code=404, detail="Change request not found")
    return cr


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
        "dept_head_approved_at": cr.dept_head_approved_at.isoformat()
        if cr.dept_head_approved_at
        else None,
        "dept_head_rejected_at": cr.dept_head_rejected_at.isoformat()
        if cr.dept_head_rejected_at
        else None,
        "dept_head_note": cr.dept_head_note,
        "admin_id": cr.admin_id,
        "admin_approved_at": cr.admin_approved_at.isoformat()
        if cr.admin_approved_at
        else None,
        "admin_rejected_at": cr.admin_rejected_at.isoformat()
        if cr.admin_rejected_at
        else None,
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
    company_id: str | None = None,
    status: str | None = None,
    personnel_id: str | None = None,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        q = select(ChangeRequest)
        if company_id:
            check_company_membership(current_user.id, company_id, session)
            q = q.where(ChangeRequest.company_id == company_id)
        else:
            mine = session.exec(
                select(CompanyMember.company_id).where(
                    CompanyMember.user_id == current_user.id
                )
            ).all()
            q = q.where(ChangeRequest.company_id.in_(mine))
        if status:
            q = q.where(ChangeRequest.status == status)
        if personnel_id:
            q = q.where(ChangeRequest.personnel_id == personnel_id)
        q = q.order_by(ChangeRequest.created_at.desc())
        return [_cr_to_dict(cr) for cr in session.exec(q).all()]


@router.get("/{cr_id}")
def get_change_request(cr_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        cr = _get_visible_cr(session, current_user, cr_id)
        return _cr_to_dict(cr)


# ── Create ────────────────────────────────────────────────────────────────────


@router.post("", status_code=201)
def create_change_request(
    body: ChangeRequestCreate,
    company_id: str,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        check_company_membership(current_user.id, company_id, session)
        personnel = session.get(Personnel, body.personnel_id)
        if not personnel or personnel.company_id != company_id:
            raise HTTPException(status_code=404, detail="Personnel not found")

        _validate_proposed(session, company_id, body.proposed)
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
        log_action(
            session,
            "create",
            "change_request",
            entity_id=cr.id,
            entity_name=cr.title,
            company_id=cr.company_id,
            user_id=current_user.id,
        )
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
        cr = _get_visible_cr(session, current_user, cr_id)
        _require_stage1(session, current_user, cr)
        if cr.status != "submitted":
            raise HTTPException(
                status_code=400,
                detail=f"CR is in '{cr.status}' status, expected 'submitted'",
            )

        _claim(session, cr, "submitted", "dept_head_approved")
        cr.status = "dept_head_approved"
        cr.dept_head_id = current_user.id
        cr.dept_head_approved_at = datetime.utcnow()
        cr.dept_head_note = body.note
        cr.updated_at = datetime.utcnow()
        session.add(cr)
        log_action(
            session,
            "approve",
            "change_request",
            entity_id=cr.id,
            entity_name=cr.title,
            company_id=cr.company_id,
            user_id=current_user.id,
            details={"stage": "dept_head"},
        )
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
        cr = _get_visible_cr(session, current_user, cr_id)
        _require_stage1(session, current_user, cr)
        if cr.status != "submitted":
            raise HTTPException(
                status_code=400, detail=f"CR is in '{cr.status}' status"
            )

        _claim(session, cr, "submitted", "rejected")
        cr.status = "rejected"
        cr.dept_head_id = current_user.id
        cr.dept_head_rejected_at = datetime.utcnow()
        cr.dept_head_note = body.note
        cr.updated_at = datetime.utcnow()
        session.add(cr)
        log_action(
            session,
            "reject",
            "change_request",
            entity_id=cr.id,
            entity_name=cr.title,
            company_id=cr.company_id,
            user_id=current_user.id,
            details={"stage": "dept_head"},
        )
        session.commit()
        session.refresh(cr)
        return _cr_to_dict(cr)


def _apply_proposed_to_db(session, cr: ChangeRequest) -> None:
    """Write proposed_json changes back to the actual Personnel / AgentConfig / Skill records."""
    proposed = json.loads(cr.proposed_json)

    if cr.change_type == "agent_config":
        personnel = session.get(Personnel, cr.personnel_id)
        if not personnel:
            return
        for field in ("name", "slug", "title", "role", "department_id"):
            if field in proposed:
                setattr(personnel, field, proposed[field])
        session.add(personnel)

        agent_cfg = session.exec(
            select(AgentConfig).where(AgentConfig.personnel_id == cr.personnel_id)
        ).first()
        if agent_cfg:
            for field in ("model", "model_version", "status", "responsible_id"):
                if field in proposed:
                    setattr(agent_cfg, field, proposed[field])
            if "provider" in proposed:
                agent_cfg.provider = proposed["provider"] or None
            agent_cfg.updated_at = datetime.utcnow()
            session.add(agent_cfg)

            # Sync per-agent skills
            if "skills" in proposed:
                existing = session.exec(
                    select(Skill).where(Skill.agent_id == agent_cfg.id)
                ).all()
                for s in existing:
                    session.delete(s)
                for s in proposed["skills"]:
                    session.add(
                        Skill(
                            agent_id=agent_cfg.id,
                            name=s.get("name", ""),
                            version=s.get("version", "1.0"),
                            description=s.get("description"),
                            skill_type=s.get("skill_type", "builtin"),
                            config_json=s.get("config_json"),
                            is_active=s.get("is_active", True),
                        )
                    )


# ── Stage 2: Admin Approval → GitHub Commit ───────────────────────────────────


@router.post("/{cr_id}/admin-approve")
def admin_approve(
    cr_id: str,
    body: ChangeRequestApprove,
    company_id: str | None = None,  # ignored for routing; kept for old clients
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        cr = _get_visible_cr(session, current_user, cr_id)
        _require_stage2(session, current_user, cr)
        if cr.status != "dept_head_approved":
            raise HTTPException(
                status_code=400,
                detail=f"CR is in '{cr.status}' status, expected 'dept_head_approved'",
            )

        if company_id and company_id != cr.company_id:
            raise HTTPException(
                status_code=400, detail="company_id does not match request"
            )

        # Mark admin approval
        _claim(session, cr, "dept_head_approved", "admin_approved")
        _validate_proposed(session, cr.company_id, json.loads(cr.proposed_json))
        cr.status = "admin_approved"
        cr.admin_id = current_user.id
        cr.admin_approved_at = datetime.utcnow()
        cr.admin_note = body.note
        cr.updated_at = datetime.utcnow()

        # Look up git config — company-specific first, fall back to global (company_id=None)
        git_cfg = session.exec(
            select(GitConfig).where(GitConfig.company_id == cr.company_id)
        ).first()
        if not git_cfg:
            git_cfg = session.exec(
                select(GitConfig).where(GitConfig.company_id.is_(None))
            ).first()

        if git_cfg:
            try:
                sha, url = commit_change_request(
                    session,
                    cr,
                    git_cfg,
                    committer_name=current_user.name,
                    committer_email=current_user.email,
                )
                cr.commit_sha = sha
                cr.commit_url = url
                cr.status = "committed"
                _apply_proposed_to_db(session, cr)
            except Exception as e:
                # Approval still saved, but commit failed — surface error
                cr.admin_note = f"{body.note or ''}\n[COMMIT ERROR: {str(e)}]".strip()
        else:
            # No git config — apply changes directly and mark done
            _apply_proposed_to_db(session, cr)
            cr.status = "committed"

        cr.updated_at = datetime.utcnow()
        session.add(cr)
        log_action(
            session,
            "approve",
            "change_request",
            entity_id=cr.id,
            entity_name=cr.title,
            company_id=cr.company_id,
            user_id=current_user.id,
            details={"stage": "admin", "commit_sha": cr.commit_sha},
        )
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
        cr = _get_visible_cr(session, current_user, cr_id)
        _require_stage2(session, current_user, cr)
        if cr.status != "dept_head_approved":
            raise HTTPException(
                status_code=400, detail=f"CR is in '{cr.status}' status"
            )

        _claim(session, cr, "dept_head_approved", "rejected")
        cr.status = "rejected"
        cr.admin_id = current_user.id
        cr.admin_rejected_at = datetime.utcnow()
        cr.admin_note = body.note
        cr.updated_at = datetime.utcnow()
        session.add(cr)
        log_action(
            session,
            "reject",
            "change_request",
            entity_id=cr.id,
            entity_name=cr.title,
            company_id=cr.company_id,
            user_id=current_user.id,
            details={"stage": "admin"},
        )
        session.commit()
        session.refresh(cr)
        return _cr_to_dict(cr)
