"""Auth endpoints: login, invite, change-password, me."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlmodel import select

from database import get_session
from models import Company, CompanyMember, User
from services.auth import (
    create_access_token,
    decode_token,
    generate_temp_password,
    hash_password,
    verify_password,
)
from services.email import send_admin_reset, send_invite, send_temp_password

router = APIRouter(prefix="/auth", tags=["auth"])

TEMP_PASSWORD_TTL_MINUTES = 30


# ── Dependencies ──────────────────────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token gerekli")
    token = authorization.split(" ", 1)[1]
    try:
        user_id = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Geçersiz token")
    with get_session() as session:
        user = session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")
    return user


def require_manager(user: User = Depends(get_current_user)) -> User:
    """Ensure caller has at least dept_head role somewhere."""
    MANAGER_ROLES = {"founder", "executive", "dept_head"}
    with get_session() as session:
        member = session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user.id,
                CompanyMember.role.in_(MANAGER_ROLES),
            )
        ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Yönetici yetkisi gerekli")
    return user


def require_founder(user: User = Depends(get_current_user)) -> User:
    with get_session() as session:
        member = session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user.id,
                CompanyMember.role == "founder",
            )
        ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Kurucu yetkisi gerekli")
    return user


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/token")
def login(body: dict):
    email: str = body.get("email", "").strip().lower()
    password: str = body.get("password", "")
    with get_session() as session:
        user = session.exec(select(User).where(User.email == email)).first()

    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Email veya şifre hatalı")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Hesap devre dışı")

    if not verify_password(password, user.password_hash):
        # If invite has expired, auto-regenerate and inform user
        if user.invite_expires_at and user.invite_expires_at < datetime.utcnow():
            _regenerate_and_send(user)
            raise HTTPException(
                status_code=401,
                detail="Geçici şifrenizin süresi dolmuştu. Yeni geçici şifre e-posta adresinize gönderildi."
            )
        raise HTTPException(status_code=401, detail="Email veya şifre hatalı")

    # Password correct — check if temp password window has expired
    if user.invite_expires_at and user.invite_expires_at < datetime.utcnow():
        _regenerate_and_send(user)
        raise HTTPException(
            status_code=401,
            detail="Geçici şifrenizin süresi dolmuştu. Yeni geçici şifre e-posta adresinize gönderildi."
        )

    # Success
    with get_session() as session:
        u = session.get(User, user.id)
        u.last_login_at = datetime.utcnow()
        # Clear invite expiry on successful use
        if u.invite_expires_at:
            u.invite_expires_at = None
        session.add(u)
        session.commit()

    token = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer", "user_id": user.id}


def _regenerate_and_send(user: User) -> None:
    """Generate new temp password and email it."""
    temp_pw = generate_temp_password()
    with get_session() as session:
        u = session.get(User, user.id)
        u.password_hash = hash_password(temp_pw)
        u.invite_expires_at = datetime.utcnow() + timedelta(minutes=TEMP_PASSWORD_TTL_MINUTES)
        u.must_change_password = True
        session.add(u)
        session.commit()
    send_temp_password(to=user.email, name=user.name, temp_password=temp_pw)


# ── Current user ──────────────────────────────────────────────────────────────

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    with get_session() as session:
        memberships = session.exec(
            select(CompanyMember).where(CompanyMember.user_id == user.id)
        ).all()
        companies = []
        for m in memberships:
            co = session.get(Company, m.company_id)
            if co:
                companies.append({
                    "company_id": m.company_id,
                    "company_name": co.name,
                    "role": m.role,
                    "scope_id": m.scope_id,
                })
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "must_change_password": user.must_change_password,
        "companies": companies,
    }


# ── Invite (temp-password flow) ───────────────────────────────────────────────

@router.post("/invite", status_code=201)
def invite_user(body: dict, caller: User = Depends(require_manager)):
    email: str = body.get("email", "").strip().lower()
    name: str = body.get("name", "").strip()
    company_id: str = body.get("company_id", "")
    role: str = body.get("role", "user")
    scope_id: Optional[str] = body.get("scope_id")

    if not email or not name or not company_id:
        raise HTTPException(status_code=422, detail="email, name, company_id zorunlu")

    with get_session() as session:
        company = session.get(Company, company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Şirket bulunamadı")

        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            user = existing
        else:
            user = User(email=email, name=name)
            session.add(user)
            session.flush()

        temp_pw = generate_temp_password()
        user.password_hash = hash_password(temp_pw)
        user.must_change_password = True
        user.invite_expires_at = datetime.utcnow() + timedelta(minutes=TEMP_PASSWORD_TTL_MINUTES)
        # Clear any stale invite/reset tokens
        user.invite_token = None
        user.reset_token = None
        user.reset_expires_at = None
        session.add(user)

        existing_member = session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user.id,
                CompanyMember.company_id == company_id,
            )
        ).first()
        if existing_member:
            existing_member.role = role
            existing_member.scope_id = scope_id
            session.add(existing_member)
        else:
            session.add(CompanyMember(
                user_id=user.id,
                company_id=company_id,
                role=role,
                scope_id=scope_id,
            ))
        session.commit()
        user_id = user.id

    send_invite(to=email, name=name, company_name=company.name, temp_password=temp_pw)
    return {"user_id": user_id, "message": "Davet emaili gönderildi"}


# ── Change password (authenticated — first-login or profile) ─────────────────

@router.post("/change-password")
def change_password(body: dict, user: User = Depends(get_current_user)):
    password: str = body.get("password", "")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="En az 8 karakterli şifre gerekli")

    with get_session() as session:
        u = session.get(User, user.id)
        u.password_hash = hash_password(password)
        u.must_change_password = False
        u.invite_expires_at = None
        u.invite_token = None
        u.reset_token = None
        u.reset_expires_at = None
        session.add(u)
        session.commit()

    token = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer"}


# ── First-time setup ──────────────────────────────────────────────────────────

@router.get("/setup-status")
def setup_status():
    with get_session() as session:
        user_count = session.exec(select(User)).all()
    return {"needs_setup": len(user_count) == 0}


@router.post("/setup", status_code=201)
def setup(body: dict):
    """Create the first admin user. Only works when no users exist."""
    with get_session() as session:
        existing = session.exec(select(User)).first()
        if existing:
            raise HTTPException(status_code=403, detail="Sistem zaten kurulmuş")

    name: str = body.get("name", "").strip()
    email: str = body.get("email", "").strip().lower()
    password: str = body.get("password", "")
    company_name: str = body.get("company_name", "").strip()

    if not name or not email or not password or not company_name:
        raise HTTPException(status_code=422, detail="name, email, password, company_name zorunlu")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Şifre en az 8 karakter olmalı")

    with get_session() as session:
        user = User(email=email, name=name, password_hash=hash_password(password), is_active=True)
        session.add(user)
        session.flush()

        import re
        slug = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-") or "sirket"
        company = Company(name=company_name, slug=slug)
        session.add(company)
        session.flush()

        session.add(CompanyMember(user_id=user.id, company_id=company.id, role="founder"))
        session.commit()
        user_id = user.id

    token = create_access_token(user_id)
    return {"access_token": token, "token_type": "bearer", "user_id": user_id}


# ── Admin: reset user password ────────────────────────────────────────────────

@router.post("/reset/{user_id}")
def admin_reset(user_id: str, caller: User = Depends(require_manager)):
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        temp_pw = generate_temp_password()
        user.password_hash = hash_password(temp_pw)
        user.must_change_password = True
        user.invite_expires_at = datetime.utcnow() + timedelta(minutes=TEMP_PASSWORD_TTL_MINUTES)
        session.add(user)
        session.commit()
        email, name = user.email, user.name

    send_admin_reset(to=email, name=name, temp_password=temp_pw)
    return {"message": "Geçici şifre gönderildi"}
