"""Telegram bot configuration — CRUD + test."""

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.auth import get_current_user
from core.security import decrypt, encrypt
from database import get_session
from models import TelegramConfig, User
from services import authz
from services.telegram import send_message, test_bot

router = APIRouter(prefix="/telegram", tags=["telegram"])

APP_URL = os.getenv("APP_URL", "http://localhost:5173")


def _founder_company_id(user: User, session, company_id: str | None) -> str:
    """The company whose bot is being configured: explicit, or the user's only
    company-wide founder membership. Never "the first membership"."""
    mine = [
        m.company_id
        for m in authz.memberships_all(session, user.id)
        if m.role == "founder" and m.scope_id is None
    ]
    if company_id:
        authz.require_role(session, user.id, company_id, {"founder"}, company_wide=True)
        return company_id
    if len(mine) != 1:
        raise HTTPException(
            status_code=422, detail="company_id gerekli (birden fazla/hiç şirket)"
        )
    return mine[0]


@router.get("/config")
def get_config(company_id: str | None = None, user: User = Depends(get_current_user)):
    with get_session() as session:
        if company_id is None:
            mine = authz.company_ids(session, user.id)
            if len(mine) != 1:
                raise HTTPException(status_code=422, detail="company_id gerekli")
            company_id = mine[0]
        authz.require_role(session, user.id, company_id, authz.MANAGERS)
        cfg = session.exec(
            select(TelegramConfig).where(TelegramConfig.company_id == company_id)
        ).first()
        if not cfg:
            return {"configured": False}
        return {
            "configured": True,
            "admin_chat_id": cfg.admin_chat_id,
            "is_active": cfg.is_active,
        }


@router.put("/config")
def save_config(
    body: dict, company_id: str | None = None, user: User = Depends(get_current_user)
):
    bot_token: str | None = body.get("bot_token")
    admin_chat_id: str | None = body.get("admin_chat_id")
    if not bot_token or not admin_chat_id:
        raise HTTPException(
            status_code=422, detail="bot_token ve admin_chat_id gerekli"
        )

    # Validate token via getMe
    info = test_bot(bot_token)
    if not info:
        raise HTTPException(
            status_code=400,
            detail="Bot token geçersiz — BotFather'dan aldığınız token'ı kontrol edin",
        )

    with get_session() as session:
        company_id = _founder_company_id(user, session, company_id)
        cfg = session.exec(
            select(TelegramConfig).where(TelegramConfig.company_id == company_id)
        ).first()
        if cfg:
            cfg.encrypted_token = encrypt(bot_token)
            cfg.admin_chat_id = admin_chat_id
            cfg.is_active = True
        else:
            cfg = TelegramConfig(
                company_id=company_id,
                encrypted_token=encrypt(bot_token),
                admin_chat_id=admin_chat_id,
            )
        session.add(cfg)
        session.commit()

    return {
        "configured": True,
        "bot_username": info.get("username"),
        "bot_name": info.get("first_name"),
        "admin_chat_id": admin_chat_id,
    }


@router.post("/test")
def test_config(company_id: str | None = None, user: User = Depends(get_current_user)):
    with get_session() as session:
        company_id = _founder_company_id(user, session, company_id)
        cfg = session.exec(
            select(TelegramConfig).where(TelegramConfig.company_id == company_id)
        ).first()
        if not cfg:
            raise HTTPException(
                status_code=404, detail="Telegram yapılandırması bulunamadı"
            )
        token = decrypt(cfg.encrypted_token)
        chat_id = cfg.admin_chat_id

    ok = send_message(
        token,
        chat_id,
        "✅ <b>3rdParty Agent Platform</b>\nTelegram bildirimleri aktif!",
    )
    if not ok:
        raise HTTPException(
            status_code=400, detail="Mesaj gönderilemedi — Chat ID'yi kontrol edin"
        )
    return {"sent": True}


@router.delete("/config", status_code=204)
def delete_config(
    company_id: str | None = None, user: User = Depends(get_current_user)
):
    with get_session() as session:
        company_id = _founder_company_id(user, session, company_id)
        cfg = session.exec(
            select(TelegramConfig).where(TelegramConfig.company_id == company_id)
        ).first()
        if cfg:
            session.delete(cfg)
            session.commit()
