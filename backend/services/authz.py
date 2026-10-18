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
    if role in ("founder", "user", "assistant_user"):
        return False
    if role == "agent_owner":
        p = session.get(Personnel, scope_id)
        return bool(p and p.company_id == company_id and p.type == "agent")
    d = session.get(Department, scope_id)
    return bool(d and d.company_id == company_id)


ASSIGNABLE_ROLES = {
    "founder",
    "executive",
    "dept_head",
    "agent_owner",
    "user",
    "assistant_user",
}
# Which membership roles may hand out which roles (company-wide memberships only,
# except that a dept_head may hand out the non-managing roles).
_GRANTORS = {
    "founder": {"founder"},
    "executive": {"founder"},
    "dept_head": {"founder", "executive"},
    "agent_owner": {"founder", "executive", "dept_head"},
    "user": {"founder", "executive", "dept_head"},
    "assistant_user": {"founder", "executive", "dept_head"},
}


def require_may_grant(
    session,
    user_id: str,
    company_id: str | None,
    role: str,
    *,
    scope_id: str | None = None,
    person=None,
):
    """Only a sufficiently senior member may assign `role` (with `scope_id`).

    Company-wide roles (scope None for founder/executive/dept_head) need a
    company-wide grantor. A grant scoped to one department may also come from a
    grantor scoped to that department; agent_owner/user grants for a person of a
    department may come from that department's head.
    """
    if not company_id:
        raise HTTPException(status_code=404, detail="Şirket bulunamadı")
    if not scope_valid(session, company_id, role, scope_id):
        raise HTTPException(status_code=422, detail="Rol için kapsam geçersiz")
    allowed_roles = _GRANTORS.get(role, {"founder"})
    dept = scope_id if role in ("executive", "dept_head") else None
    if role in ("agent_owner", "user", "assistant_user") and person is not None:
        dept = person.department_id
    if not has_role(session, user_id, company_id, allowed_roles, department_id=dept):
        raise HTTPException(status_code=403, detail="Bu rolü atama yetkiniz yok")
    if role == "agent_owner":
        # The grant also hands over an agent: the grantor needs authority over *it*.
        from models import Personnel

        agent = session.get(Personnel, scope_id) if scope_id else None
        if agent is None or not has_role(
            session,
            user_id,
            company_id,
            allowed_roles,
            department_id=agent.department_id,
        ):
            raise HTTPException(status_code=403, detail="Bu ajan için yetkiniz yok")


def lock_company(session, company_id: str) -> None:
    """Serialise membership changes of one company (row lock on PostgreSQL)."""
    from models import Company

    session.exec(select(Company).where(Company.id == company_id).with_for_update())


def would_orphan_founders(
    session, member: CompanyMember, *, keep: bool = False
) -> bool:
    """True if removing / changing `member` leaves no active company-wide founder.

    `keep=True` means the member stays a company-wide founder (nothing to protect).
    """
    from models import User

    if keep or member.role != "founder" or member.scope_id is not None:
        return False
    lock_company(session, member.company_id)
    others = session.exec(
        select(CompanyMember).where(
            CompanyMember.company_id == member.company_id,
            CompanyMember.role == "founder",
            CompanyMember.scope_id.is_(None),
            CompanyMember.id != member.id,
        )
    ).all()
    for o in others:
        u = session.get(User, o.user_id)
        if u is not None and u.is_active:
            return False
    return True


def controls_account(session, caller_id: str, target_id: str, roles=FINAL) -> bool:
    """The caller holds a company-wide `roles` membership in *every* company the
    target account belongs to (so changing the account cannot touch a tenant the
    caller has no authority over). An account with no company is nobody's."""
    theirs = {m.company_id for m in memberships_all(session, target_id)}
    if not theirs:
        return False
    return all(
        has_role(session, caller_id, c, roles, company_wide=True) for c in theirs
    )


def is_assistant_only(session, user_id: str, company_id: str | None) -> bool:
    """The user is in the company only as `assistant_user` (ADR-0022 §7): the
    department web view, with no company-wide lists and no editing."""
    mine = memberships(session, user_id, company_id)
    return bool(mine) and all(m.role == "assistant_user" for m in mine)


def deny_assistant(session, user_id: str, company_id: str | None) -> None:
    """Company-wide lists and configuration are not part of the assistant view."""
    if is_assistant_only(session, user_id, company_id):
        raise HTTPException(
            status_code=403, detail="Bu görünümde şirket geneli listeler yok"
        )
