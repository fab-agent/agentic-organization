import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.audit import log_action
from api.auth import get_current_user, require_manager
from core.security import decrypt, encrypt
from database import get_session
from models import AppConfig, ProviderKey, User
from schemas import ConfigPatch, CustomEndpointCreate, SetProviderKey
from services.provider_service import (
    CUSTOM_PREFIX,
    LOCAL_PROVIDERS,
    PROVIDER_CONFIGS,
    SUPPORTED_PROVIDERS,
    detect_qwen_base_url,
    get_provider_models,
    is_custom_provider,
    list_openai_compatible_models,
    probe_chat_completion,
    save_model_capabilities,
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
    return session.exec(
        select(ProviderKey).where(ProviderKey.provider == provider)
    ).first()


def _provider_status_dict(
    row: ProviderKey | None, provider: str, plain_key: str | None = None
) -> dict:
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
    models = (
        get_provider_models(provider, plain_key, base_url=row.base_url)
        if row.status == "active"
        else []
    )
    if models:
        try:
            save_model_capabilities(models)
        except Exception:
            pass  # never block the response
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
            found = get_provider_models(row.provider, plain_key, base_url=row.base_url)
            if not found and is_custom_provider(row.provider):
                found = [
                    {"provider": row.provider, "id": m, "name": m, "type": "chat"}
                    for m in json.loads(row.models_json or "[]")
                ]
            models.extend(found)
        return models


# ── Custom OpenAI-compatible endpoints (ADR-0016) ─────────────────────────────
#
# Any server that speaks the OpenAI chat-completions protocol — vLLM, LiteLLM,
# Ollama on another host, an in-house gateway, a cloud API — added by base URL +
# token. Stored as ProviderKey rows named "custom:<slug>"; agents reference them
# through AgentConfig.provider or a "custom:<slug>/<model>" model reference.
# Declared before the generic /providers/{provider}/… routes so that
# /providers/custom/<slug> never matches them.


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:40]
    if not slug:
        raise HTTPException(status_code=422, detail="Endpoint name is required")
    return slug


def _normalize_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not re.match(r"^https?://", url):
        raise HTTPException(
            status_code=422, detail="base_url must start with http:// or https://"
        )
    for suffix in ("/chat/completions", "/models"):
        url = url.removesuffix(suffix)
    return url


def _validate_endpoint(
    base_url: str, api_key: str, manual_models: list[str]
) -> tuple[bool, list[str]]:
    """(reachable, model ids). /models first; else a one-token completion."""
    ids = list_openai_compatible_models(base_url, api_key)
    if ids is not None:
        return True, ids or manual_models
    if manual_models and probe_chat_completion(base_url, api_key, manual_models[0]):
        return True, manual_models
    return False, manual_models


def _custom_dict(row: ProviderKey) -> dict:
    return {
        "provider": row.provider,
        "slug": row.provider.removeprefix(CUSTOM_PREFIX),
        "display_name": row.display_name or row.provider.removeprefix(CUSTOM_PREFIX),
        "base_url": row.base_url,
        "status": row.status,
        "has_key": bool(row.encrypted_key) and bool(decrypt(row.encrypted_key)),
        "models": json.loads(row.models_json or "[]"),
        "last_tested": row.last_tested.isoformat() if row.last_tested else None,
    }


def _custom_row(session, slug: str) -> ProviderKey:
    row = _provider_row(session, CUSTOM_PREFIX + slug)
    if not row:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return row


@router.get("/providers/custom")
def list_custom_endpoints(_: User = Depends(get_current_user)):
    with get_session() as session:
        rows = session.exec(
            select(ProviderKey).where(ProviderKey.provider.startswith(CUSTOM_PREFIX))
        ).all()
        return [_custom_dict(r) for r in rows]


@router.post("/providers/custom", status_code=201)
def upsert_custom_endpoint(
    body: CustomEndpointCreate, _: User = Depends(require_manager)
):
    slug = _slugify(body.name)
    base_url = _normalize_base_url(body.base_url)
    api_key = (body.api_key or "").strip()
    manual = [m.strip() for m in (body.models or []) if m and m.strip()]
    ok, models = _validate_endpoint(base_url, api_key, manual)

    with get_session() as session:
        provider = CUSTOM_PREFIX + slug
        row = _provider_row(session, provider)
        is_update = row is not None
        if not row:
            row = ProviderKey(provider=provider, encrypted_key="")
        row.display_name = body.name.strip()
        row.base_url = base_url
        row.encrypted_key = encrypt(api_key)
        row.models_json = json.dumps(models)
        row.status = "active" if ok else "invalid"
        row.last_tested = datetime.utcnow()
        session.add(row)
        log_action(
            session,
            "update" if is_update else "create",
            "provider_key",
            entity_name=provider,
            details={"base_url": base_url, "valid": ok, "models": len(models)},
        )
        session.commit()
        session.refresh(row)
        return _custom_dict(row)


@router.post("/providers/custom/{slug}/test")
def test_custom_endpoint(slug: str, _: User = Depends(require_manager)):
    with get_session() as session:
        row = _custom_row(session, slug)
        api_key = decrypt(row.encrypted_key) if row.encrypted_key else ""
        ok, models = _validate_endpoint(
            row.base_url or "", api_key, json.loads(row.models_json or "[]")
        )
        row.models_json = json.dumps(models)
        row.status = "active" if ok else "invalid"
        row.last_tested = datetime.utcnow()
        session.add(row)
        log_action(
            session,
            "test",
            "provider_key",
            entity_name=row.provider,
            details={"valid": ok},
        )
        session.commit()
        session.refresh(row)
        return _custom_dict(row)


@router.delete("/providers/custom/{slug}", status_code=204)
def delete_custom_endpoint(slug: str, _: User = Depends(require_manager)):
    with get_session() as session:
        row = _custom_row(session, slug)
        log_action(session, "delete", "provider_key", entity_name=row.provider)
        session.delete(row)
        session.commit()


@router.post("/providers/{provider}/key", status_code=201)
def set_provider_key(
    provider: str, body: SetProviderKey, _: User = Depends(require_manager)
):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    if provider in LOCAL_PROVIDERS:
        # Local providers: key is ignored, base_url is what matters
        plain_key = "local"
        base_url = (body.base_url or "").strip() or PROVIDER_CONFIGS[provider].get(
            "default_base_url", ""
        )
        valid = test_provider_key(provider, plain_key, base_url=base_url)
        local_models = (
            list_openai_compatible_models(base_url, plain_key) if valid else None
        )
    else:
        local_models = None
        plain_key = body.key.strip()
        if not plain_key:
            raise HTTPException(status_code=422, detail="Key cannot be empty")
        if provider == "qwen":
            base_url = detect_qwen_base_url(plain_key)
            valid = base_url is not None
        else:
            base_url = None
            valid = test_provider_key(provider, plain_key)

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
            if local_models is not None:
                row.models_json = json.dumps(local_models)
            session.add(row)
        else:
            row = ProviderKey(
                provider=provider,
                encrypted_key=encrypted,
                status="active" if valid else "invalid",
                base_url=base_url,
                models_json=json.dumps(local_models)
                if local_models is not None
                else None,
                last_tested=now,
            )
            session.add(row)
        log_action(
            session,
            "update" if is_update else "create",
            "provider_key",
            entity_name=provider,
        )
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
            # Soft-delete: keep row so env-sync on restart doesn't re-add this key
            row.encrypted_key = ""
            row.status = "unconfigured"
            row.base_url = None
            row.last_tested = None
            session.add(row)
            session.commit()


@router.post("/providers/{provider}/test")
def test_existing_key(provider: str, _: User = Depends(require_manager)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    with get_session() as session:
        row = _provider_row(session, provider)
        if not row:
            raise HTTPException(
                status_code=404, detail="No key configured for this provider"
            )

        plain_key = decrypt(row.encrypted_key)
        if provider in LOCAL_PROVIDERS:
            valid = test_provider_key(provider, plain_key, base_url=row.base_url)
        elif provider == "qwen":
            base_url = detect_qwen_base_url(plain_key)
            valid = base_url is not None
            row.base_url = base_url
        else:
            valid = test_provider_key(provider, plain_key)
        row.status = "active" if valid else "invalid"
        row.last_tested = datetime.utcnow()
        session.add(row)
        log_action(
            session,
            "test",
            "provider_key",
            entity_name=provider,
            details={"valid": valid},
        )
        session.commit()
        session.refresh(row)
        return _provider_status_dict(row, provider, plain_key if valid else None)
