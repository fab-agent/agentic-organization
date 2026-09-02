import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.auth import get_current_user, require_manager
from database import get_session
from models import ChangeRequest, Policy, PolicyConfig, User
from services.policy_engine import VALID_EFFECTS, VALID_MODES, resolve_mode

router = APIRouter(tags=["policies"])


class PolicyCreate(BaseModel):
    company_id: str
    name: str
    slug: str
    content: str = ""
    scope: str = "company"  # company | department | agent
    department_id: str | None = None
    agent_config_id: str | None = None


class PolicyUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    content: str | None = None
    scope: str | None = None
    department_id: str | None = None
    agent_config_id: str | None = None
    is_active: bool | None = None


def _policy_dict(p: Policy) -> dict:
    return {
        "id": p.id,
        "company_id": p.company_id,
        "department_id": p.department_id,
        "agent_config_id": p.agent_config_id,
        "name": p.name,
        "slug": p.slug,
        "content": p.content,
        "scope": p.scope,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


# ── Policy Engine enforcement config (ADR-0005) ─────────────────────────────


class PolicyConfigSet(BaseModel):
    company_id: str
    scope: str = "company"  # company | department | agent
    scope_id: str | None = None  # department.id or agentconfig.id
    mode: str | None = None  # off | dry_run | enforce | null (=inherit)
    default_effect: str | None = None  # allow | ask | deny | null (=inherit)


@router.get("/policies/config")
def list_policy_config(
    company_id: str,
    department_id: str | None = None,
    agent_config_id: str | None = None,
    _: User = Depends(get_current_user),
):
    """Raw PolicyConfig rows for the company + the resolved effective setting."""
    with get_session() as session:
        rows = session.exec(
            select(PolicyConfig).where(PolicyConfig.company_id == company_id)
        ).all()
    mode, default_effect = resolve_mode(company_id, department_id, agent_config_id)
    return {
        "rows": [
            {
                "id": r.id,
                "scope": r.scope,
                "scope_id": r.scope_id,
                "mode": r.mode,
                "default_effect": r.default_effect,
            }
            for r in rows
        ],
        "effective": {"mode": mode, "default_effect": default_effect},
    }


@router.put("/policies/config")
def set_policy_config(body: PolicyConfigSet, _: User = Depends(require_manager)):
    if body.scope not in ("company", "department", "agent"):
        raise HTTPException(status_code=422, detail=f"bad scope: {body.scope}")
    if body.mode is not None and body.mode not in VALID_MODES:
        raise HTTPException(status_code=422, detail=f"bad mode: {body.mode}")
    if body.default_effect is not None and body.default_effect not in VALID_EFFECTS:
        raise HTTPException(
            status_code=422, detail=f"bad default_effect: {body.default_effect}"
        )
    if body.scope != "company" and not body.scope_id:
        raise HTTPException(
            status_code=422, detail="scope_id required for department/agent scope"
        )

    scope_id = None if body.scope == "company" else body.scope_id
    with get_session() as session:
        q = select(PolicyConfig).where(
            PolicyConfig.company_id == body.company_id,
            PolicyConfig.scope == body.scope,
        )
        q = (
            q.where(PolicyConfig.scope_id == scope_id)
            if scope_id
            else q.where(PolicyConfig.scope_id.is_(None))
        )
        row = session.exec(q).first()
        if row:
            row.mode = body.mode
            row.default_effect = body.default_effect
            row.updated_at = datetime.utcnow()
        else:
            row = PolicyConfig(
                company_id=body.company_id,
                scope=body.scope,
                scope_id=scope_id,
                mode=body.mode,
                default_effect=body.default_effect,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {
            "id": row.id,
            "scope": row.scope,
            "scope_id": row.scope_id,
            "mode": row.mode,
            "default_effect": row.default_effect,
        }


@router.get("/policies")
def list_policies(
    company_id: str | None = None,
    department_id: str | None = None,
    agent_config_id: str | None = None,
    scope: str | None = None,
    _: User = Depends(get_current_user),
):
    with get_session() as session:
        q = select(Policy)
        if company_id:
            q = q.where(Policy.company_id == company_id)
        if department_id:
            q = q.where(Policy.department_id == department_id)
        if agent_config_id:
            q = q.where(Policy.agent_config_id == agent_config_id)
        if scope:
            q = q.where(Policy.scope == scope)
        rows = session.exec(q.order_by(Policy.scope, Policy.name)).all()
        return [_policy_dict(p) for p in rows]


@router.post("/policies", status_code=201)
def create_policy(body: PolicyCreate, _: User = Depends(require_manager)):
    with get_session() as session:
        policy = Policy(
            company_id=body.company_id,
            name=body.name,
            slug=body.slug,
            content=body.content,
            scope=body.scope,
            department_id=body.department_id or None,
            agent_config_id=body.agent_config_id or None,
        )
        session.add(policy)
        session.commit()
        session.refresh(policy)
        return _policy_dict(policy)


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str, _: User = Depends(get_current_user)):
    with get_session() as session:
        p = session.get(Policy, policy_id)
        if not p:
            raise HTTPException(status_code=404, detail="Policy not found")
        return _policy_dict(p)


@router.put("/policies/{policy_id}")
def update_policy(
    policy_id: str,
    body: PolicyUpdate,
    propose: bool = False,
    personnel_id: str | None = None,
    user: User = Depends(require_manager),
):
    """
    Direct update (managers+) or propose a CR.
    If propose=true, creates a ChangeRequest instead of applying.
    """
    with get_session() as session:
        p = session.get(Policy, policy_id)
        if not p:
            raise HTTPException(status_code=404, detail="Policy not found")

        if propose and personnel_id:
            original = {"name": p.name, "content": p.content, "scope": p.scope}
            proposed = {k: v for k, v in body.model_dump().items() if v is not None}
            cr = ChangeRequest(
                company_id=p.company_id,
                personnel_id=personnel_id,
                change_type="policy",
                title=f"Politika güncelleme: {p.name}",
                proposed_json=json.dumps({"policy_id": policy_id, **proposed}),
                original_json=json.dumps(original),
                status="submitted",
            )
            session.add(cr)
            session.commit()
            session.refresh(cr)
            return {"change_request_id": cr.id, "status": "submitted"}

        updates = body.model_dump(exclude_none=True)
        # Company-scoped policies are always active — ignore is_active overrides
        if p.scope == "company":
            updates.pop("is_active", None)
        for field, val in updates.items():
            setattr(p, field, val)
        p.updated_at = datetime.utcnow()
        session.add(p)
        session.commit()
        session.refresh(p)
        return _policy_dict(p)


@router.delete("/policies/{policy_id}", status_code=204)
def delete_policy(policy_id: str, _: User = Depends(require_manager)):
    with get_session() as session:
        p = session.get(Policy, policy_id)
        if not p:
            raise HTTPException(status_code=404, detail="Policy not found")
        session.delete(p)
        session.commit()
