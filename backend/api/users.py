"""User & CompanyMember management (founder-only, per company).

A founder administers the people of *their own* companies: they see only the
memberships in companies they found, and may change an account itself only when
every company the account belongs to is theirs.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import Company, CompanyMember, Department, Personnel, User
from services import authz

router = APIRouter(prefix="/users", tags=["users"])

_ROLES = {"founder", "executive", "dept_head", "agent_owner", "user"}


def _my_companies(session, user: User) -> set[str]:
    """Companies where the caller is a company-wide founder."""
    return {
        m.company_id
        for m in authz.memberships_all(session, user.id)
        if m.role == "founder" and m.scope_id is None
    }


def _require_any_founder(user: User = Depends(get_current_user)) -> User:
    with get_session() as session:
        if not _my_companies(session, user):
            raise HTTPException(status_code=403, detail="Kurucu yetkisi gerekli")
    return user


def _controls_account(session, caller: User, target_id: str) -> bool:
    """Caller is founder of every company the target account belongs to."""
    mine = _my_companies(session, caller)
    theirs = {
        m.company_id
        for m in session.exec(
            select(CompanyMember).where(CompanyMember.user_id == target_id)
        ).all()
    }
    return bool(theirs) and theirs <= mine


def _last_founder(session, member: CompanyMember) -> bool:
    if member.role != "founder":
        return False
    others = session.exec(
        select(CompanyMember).where(
            CompanyMember.company_id == member.company_id,
            CompanyMember.role == "founder",
            CompanyMember.id != member.id,
        )
    ).all()
    return not others


def _user_to_dict(user: User, session, only: set[str] | None = None) -> dict:
    memberships = session.exec(
        select(CompanyMember).where(CompanyMember.user_id == user.id)
    ).all()
    if only is not None:
        memberships = [m for m in memberships if m.company_id in only]
    companies = []
    for m in memberships:
        co = session.get(Company, m.company_id)
        scope_name = None
        if m.scope_id:
            dept = session.get(Department, m.scope_id)
            if dept:
                scope_name = dept.name
            else:
                agent = session.get(Personnel, m.scope_id)
                if agent:
                    scope_name = agent.name
        companies.append(
            {
                "membership_id": m.id,
                "company_id": m.company_id,
                "company_name": co.name if co else None,
                "role": m.role,
                "scope_id": m.scope_id,
                "scope_name": scope_name,
            }
        )
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat(),
        "companies": companies,
    }


@router.get("")
def list_users(company_id: str, caller: User = Depends(_require_any_founder)):
    with get_session() as session:
        authz.require_role(
            session, caller.id, company_id, {"founder"}, company_wide=True
        )
        member_ids = [
            m.user_id
            for m in session.exec(
                select(CompanyMember).where(CompanyMember.company_id == company_id)
            ).all()
        ]
        users = session.exec(select(User).where(User.id.in_(member_ids))).all()
        return [_user_to_dict(u, session, {company_id}) for u in users]


@router.get("/{user_id}")
def get_user(user_id: str, caller: User = Depends(_require_any_founder)):
    with get_session() as session:
        user = session.get(User, user_id)
        mine = _my_companies(session, caller)
        shared = session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user_id, CompanyMember.company_id.in_(mine)
            )
        ).first()
        if not user or not shared:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        return _user_to_dict(user, session, mine)


@router.patch("/{user_id}")
def update_user(user_id: str, body: dict, caller: User = Depends(_require_any_founder)):
    with get_session() as session:
        user = session.get(User, user_id)
        if not user or not _controls_account(session, caller, user_id):
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        if "name" in body:
            user.name = str(body["name"])
        if "is_active" in body:
            if user.id == caller.id and body["is_active"] is False:
                raise HTTPException(status_code=400, detail="Kendinizi kapatamazsınız")
            user.is_active = bool(body["is_active"])
        session.add(user)
        session.commit()
        session.refresh(user)
        return _user_to_dict(user, session, _my_companies(session, caller))


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, caller: User = Depends(_require_any_founder)):
    with get_session() as session:
        user = session.get(User, user_id)
        if not user or not _controls_account(session, caller, user_id):
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        if user.id == caller.id:
            raise HTTPException(status_code=400, detail="Kendinizi silemezsiniz")
        members = session.exec(
            select(CompanyMember).where(CompanyMember.user_id == user_id)
        ).all()
        if any(_last_founder(session, m) for m in members):
            raise HTTPException(status_code=409, detail="Son kurucu silinemez")
        for m in members:
            session.delete(m)
        session.delete(user)
        session.commit()


# ── Membership management ─────────────────────────────────────────────────────


@router.get("/{user_id}/memberships")
def list_memberships(user_id: str, caller: User = Depends(_require_any_founder)):
    with get_session() as session:
        return session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user_id,
                CompanyMember.company_id.in_(_my_companies(session, caller)),
            )
        ).all()


def _my_membership(session, caller: User, member_id: str) -> CompanyMember:
    member = session.get(CompanyMember, member_id)
    if not member or member.company_id not in _my_companies(session, caller):
        raise HTTPException(status_code=404, detail="Üyelik bulunamadı")
    return member


@router.patch("/memberships/{member_id}")
def update_membership(
    member_id: str, body: dict, caller: User = Depends(_require_any_founder)
):
    with get_session() as session:
        member = _my_membership(session, caller, member_id)
        role = body.get("role", member.role)
        scope_id = body["scope_id"] if "scope_id" in body else member.scope_id
        if role not in _ROLES:
            raise HTTPException(status_code=422, detail="Bilinmeyen rol")
        if not authz.scope_valid(session, member.company_id, role, scope_id):
            raise HTTPException(status_code=422, detail="Rol için kapsam geçersiz")
        if _last_founder(session, member) and (role != "founder" or scope_id):
            raise HTTPException(status_code=409, detail="Son kurucu değiştirilemez")
        member.role, member.scope_id = role, scope_id
        session.add(member)
        session.commit()
        session.refresh(member)
        return member


@router.delete("/memberships/{member_id}", status_code=204)
def delete_membership(member_id: str, caller: User = Depends(_require_any_founder)):
    with get_session() as session:
        member = _my_membership(session, caller, member_id)
        if _last_founder(session, member):
            raise HTTPException(status_code=409, detail="Son kurucu silinemez")
        session.delete(member)

        session.commit()
