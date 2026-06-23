from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from api.audit import log_action
from core.security import encrypt, decrypt
from database import get_session
from models import AppConfig, ProviderKey
from schemas import ConfigPatch, SetProviderKey
from services.provider_service import (
    PROVIDER_CONFIGS,
    SUPPORTED_PROVIDERS,
    get_provider_models,
    test_provider_key,
)

router = APIRouter(tags=["providers"])


# ── Platform Config ────────────────────────────────────────────────────────────

@router.get("/config")
def get_config():
    with get_session() as session:
        rows = session.exec(select(AppConfig)).all()
        return {r.key: r.value for r in rows}


@router.patch("/config")
def patch_config(body: ConfigPatch):
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


def _provider_status_dict(row: ProviderKey | None, provider: str) -> dict:
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
    return {
        "provider": provider,
        "display_name": cfg["display_name"],
        "status": row.status,
        "has_key": True,
        "models": cfg["models"] if row.status == "active" else [],
        "last_tested": row.last_tested.isoformat() if row.last_tested else None,
    }


@router.get("/providers/status")
def list_provider_status():
    with get_session() as session:
        return [
            _provider_status_dict(_provider_row(session, p), p)
            for p in SUPPORTED_PROVIDERS
        ]


@router.get("/providers/models")
def list_available_models():
    """Returns models from all active providers — used by the agent model picker."""
    with get_session() as session:
        active = session.exec(
            select(ProviderKey).where(ProviderKey.status == "active")
        ).all()
        models = []
        for row in active:
            models.extend(get_provider_models(row.provider))
        return models


@router.post("/providers/{provider}/key", status_code=201)
def set_provider_key(provider: str, body: SetProviderKey):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    plain_key = body.key.strip()
    if not plain_key:
        raise HTTPException(status_code=422, detail="Key cannot be empty")

    valid = test_provider_key(provider, plain_key)
    encrypted = encrypt(plain_key)
    now = datetime.utcnow()

    with get_session() as session:
        row = _provider_row(session, provider)
        is_update = row is not None
        if row:
            row.encrypted_key = encrypted
            row.status = "active" if valid else "invalid"
            row.last_tested = now
            session.add(row)
        else:
            row = ProviderKey(
                provider=provider,
                encrypted_key=encrypted,
                status="active" if valid else "invalid",
                last_tested=now,
            )
            session.add(row)
        log_action(session, "update" if is_update else "create", "provider_key", entity_name=provider)
        session.commit()
        session.refresh(row)
        return _provider_status_dict(row, provider)


@router.delete("/providers/{provider}/key", status_code=204)
def delete_provider_key(provider: str):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    with get_session() as session:
        row = _provider_row(session, provider)
        if row:
            log_action(session, "delete", "provider_key", entity_name=provider)
            session.delete(row)
            session.commit()


@router.post("/providers/{provider}/test")
def test_existing_key(provider: str):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    with get_session() as session:
        row = _provider_row(session, provider)
        if not row:
            raise HTTPException(status_code=404, detail="No key configured for this provider")

        plain_key = decrypt(row.encrypted_key)
        valid = test_provider_key(provider, plain_key)
        row.status = "active" if valid else "invalid"
        row.last_tested = datetime.utcnow()
        session.add(row)
        log_action(session, "test", "provider_key", entity_name=provider, details={"valid": valid})
        session.commit()
        session.refresh(row)
        return _provider_status_dict(row, provider)
