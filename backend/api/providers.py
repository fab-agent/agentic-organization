from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.audit import log_action
from api.auth import get_current_user, require_manager
from core.security import encrypt, decrypt
from database import get_session
from models import AppConfig, ProviderKey, User
from schemas import ConfigPatch, SetProviderKey
from services.provider_service import (
    PROVIDER_CONFIGS,
    SUPPORTED_PROVIDERS,
    detect_qwen_base_url,
    get_provider_models,
    test_provider_key,
)

router = APIRouter(tags=["providers"])


# ── Platform Config ────────────────────────────────────────────────────────────

@router.get("/config")
def get_config(_: User = Depends(get_current_user)):
    with get_session() as session:
        rows = session.exec(select(AppConfig)).all()
        return {r.key: r.value for r in rows}


@router.patch("/config")
def patch_config(body: ConfigPatch, _: User = Depends(require_manager)):
    with get_session() as session:
        for key, value in body.data.items():
            existing = session.get(AppConfig, key)
            if existing:
                existing.value = value
                session.add(existing)
            else:
                session.add(AppConfig(key=key, value=value))
        session.commit()
    return {"ok": True}


# ── Providers ──────────────────────────────────────────────────────────────────

def _provider_row(session, provider: str) -> ProviderKey | None:
    return session.exec(select(ProviderKey).where(ProviderKey.provider == provider)).first()


def _provider_status_dict(row: ProviderKey | None, provider: str, plain_key: str | None = None) -> dict:
    cfg = PROVIDER_CONFIGS[provider]
    if not row or row.status == "unconfigured":
        return {
            "provider": provider,
            "display_name": cfg["display_name"],
            "status": "unconfigured",
            "has_key": False,
            "models": [],
            "last_tested": None,
        }
    models = get_provider_models(provider, plain_key) if row.status == "active" else []
    return {
        "provider": provider,
        "display_name": cfg["display_name"],
        "status": row.status,
        "has_key": True,
        "models": models,
        "last_tested": row.last_tested.isoformat() if row.last_tested else None,
    }


@router.get("/providers/status")
def list_provider_status(_: User = Depends(get_current_user)):
    with get_session() as session:
        return [
            _provider_status_dict(_provider_row(session, p), p)
            for p in SUPPORTED_PROVIDERS
        ]


@router.get("/providers/models")
def list_available_models(_: User = Depends(get_current_user)):
    """Returns models from all active providers with pricing metadata."""
    with get_session() as session:
        active = session.exec(
            select(ProviderKey).where(ProviderKey.status == "active")
        ).all()
        models = []
        for row in active:
            plain_key = decrypt(row.encrypted_key)
            models.extend(get_provider_models(row.provider, plain_key))
        return models


@router.post("/providers/{provider}/key", status_code=201)
def set_provider_key(provider: str, body: SetProviderKey,
                     _: User = Depends(require_manager)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    plain_key = body.key.strip()
    if not plain_key:
        raise HTTPException(status_code=422, detail="Key cannot be empty")

    base_url = detect_qwen_base_url(plain_key) if provider == "qwen" else None
    valid = (base_url is not None) if provider == "qwen" else test_provider_key(provider, plain_key)
    encrypted = encrypt(plain_key)
    now = datetime.utcnow()

    with get_session() as session:
        row = _provider_row(session, provider)
        is_update = row is not None
        if row:
            row.encrypted_key = encrypted
            row.status = "active" if valid else "invalid"
            row.base_url = base_url
            row.last_tested = now
            session.add(row)
        else:
            row = ProviderKey(
                provider=provider,
                encrypted_key=encrypted,
                status="active" if valid else "invalid",
                base_url=base_url,
                last_tested=now,
            )
            session.add(row)
        log_action(session, "update" if is_update else "create", "provider_key", entity_name=provider)
        session.commit()
        session.refresh(row)
        return _provider_status_dict(row, provider, plain_key if valid else None)


@router.delete("/providers/{provider}/key", status_code=204)
def delete_provider_key(provider: str, _: User = Depends(require_manager)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    with get_session() as session:
        row = _provider_row(session, provider)
        if row:
            log_action(session, "delete", "provider_key", entity_name=provider)
            session.delete(row)
            session.commit()


@router.post("/providers/{provider}/test")
def test_existing_key(provider: str, _: User = Depends(require_manager)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    with get_session() as session:
        row = _provider_row(session, provider)
        if not row:
            raise HTTPException(status_code=404, detail="No key configured for this provider")

        plain_key = decrypt(row.encrypted_key)
        if provider == "qwen":
            base_url = detect_qwen_base_url(plain_key)
            valid = base_url is not None
            row.base_url = base_url
        else:
            valid = test_provider_key(provider, plain_key)
        row.status = "active" if valid else "invalid"
        row.last_tested = datetime.utcnow()
        session.add(row)
        log_action(session, "test", "provider_key", entity_name=provider, details={"valid": valid})
        session.commit()
        session.refresh(row)
        return _provider_status_dict(row, provider)
