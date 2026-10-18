"""Resource-scoped authorisation helpers.

`api.auth.require_manager` only proves a managing role *somewhere*; these helpers
check the role in the company (and department) that owns the resource.

A `CompanyMember` carries a role and an optional `scope_id`:
  - founder/executive/dept_head: None = company-wide, else a department id;
  - agent_owner: the agent's personnel id (never a department).
Role and scope are always evaluated on the same membership row.
"""

from fastapi import HTTPException
from sqlmodel import select

from models import CompanyMember

MANAGERS = frozenset({"founder", "executive", "dept_head"})
FINAL = frozenset({"founder", "executive"})


def memberships(session, user_id: str, company_id: str | None) -> list[CompanyMember]:
    if not company_id:
        return []
    return list(
        session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user_id,
                CompanyMember.company_id == company_id,
            )
        ).all()
    )


def memberships_all(session, user_id: str) -> list[CompanyMember]:
    return list(
        session.exec(
            select(CompanyMember).where(CompanyMember.user_id == user_id)
        ).all()
    )


def company_ids(session, user_id: str) -> list[str]:
    return list(
        session.exec(
            select(CompanyMember.company_id).where(CompanyMember.user_id == user_id)
        ).all()
    )


def is_member(session, user_id: str, company_id: str | None) -> bool:
    return bool(memberships(session, user_id, company_id))


def has_role(
    session,
    user_id: str,
    company_id: str | None,
    roles: frozenset[str] | set[str],
    *,
    department_id: str | None = None,
    company_wide: bool = False,
) -> bool:
    """True if one membership has a role in `roles` and a fitting scope.

    A company-wide membership (scope None) always fits. A department-scoped one fits
    only when `department_id` is given and equal, unless `company_wide` is demanded.
    """
    for m in memberships(session, user_id, company_id):
        if m.role not in roles:
            continue
        if m.scope_id is None:
            return True
        if not company_wide and department_id and m.scope_id == department_id:
            return True
    return False


def require_member(session, user_id: str, company_id: str | None) -> None:
    """404 (no existence leak) unless the user belongs to the company."""
    if not is_member(session, user_id, company_id):
        raise HTTPException(status_code=404, detail="Not found")


def require_role(
    session,
    user_id: str,
    company_id: str | None,
    roles: frozenset[str] | set[str],
    *,
    department_id: str | None = None,
    company_wide: bool = False,
    detail: str = "Bu işlem için yetkiniz yok",
) -> None:
    """404 for outsiders, 403 for members without the role/scope."""
    require_member(session, user_id, company_id)
    if not has_role(
        session,
        user_id,
        company_id,
        roles,
        department_id=department_id,
        company_wide=company_wide,
    ):
        raise HTTPException(status_code=403, detail=detail)


def can_manage_agent(session, user_id: str, person) -> bool:
    """May this user act for / configure operations of the agent `person`?

    Company-wide founder/executive/dept_head, the managers of the agent's
    department, the agent's owner (agent_owner scoped to it) and the responsible
    human. Role and scope are read from the same membership row.
    """
    from models import AgentConfig, Personnel

    if has_role(
        session,
        user_id,
        person.company_id,
        MANAGERS,
        department_id=person.department_id,
    ):
        return True
    for m in memberships(session, user_id, person.company_id):
        if m.role == "agent_owner" and m.scope_id == person.id:
            return True
    cfg = session.exec(
        select(AgentConfig).where(AgentConfig.personnel_id == person.id)
    ).first()
    if cfg and cfg.responsible_id:
        mine = session.exec(
            select(Personnel).where(
                Personnel.user_id == user_id,
                Personnel.company_id == person.company_id,
            )
        ).all()
        if any(p.id == cfg.responsible_id for p in mine):
            return True
    return False


def agent_is_active(session, person_id: str) -> bool:
    """Only an `active` agent may run (not draft, not inactive)."""
    from models import AgentConfig

    cfg = session.exec(
        select(AgentConfig).where(AgentConfig.personnel_id == person_id)
    ).first()
    return bool(cfg and cfg.status == "active")


def scope_valid(session, company_id: str, role: str, scope_id: str | None) -> bool:
    """Is `scope_id` a legal scope for `role` in this company?

    founder/user: none. executive/dept_head: none (company-wide) or a department of
    the company. agent_owner: an agent of the company (always required).
    """
    from models import Department, Personnel

    if scope_id is None:
        return role != "agent_owner"
    if role in ("founder", "user"):
        return False
    if role == "agent_owner":
        p = session.get(Personnel, scope_id)
        return bool(p and p.company_id == company_id and p.type == "agent")
    d = session.get(Department, scope_id)
    return bool(d and d.company_id == company_id)
