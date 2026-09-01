"""
Workstation LLM Gateway — OpenAI-compatible proxy (ADR-0004).

All model traffic from workstation agents (`3pa` → opencode) goes through here so
that, regardless of what the client does:
  - the organisation's own OpenAI-compatible upstream is used (BYO endpoint),
  - every call is written to the audit log (ADR-0006),
  - model allow-lists / per-persona quota / rate limits are enforced (Faz 2).

Status: Faz 0 skeleton. Working passthrough + audit. TODOs mark where later
phases plug in (policy decisions, quota, hash-chained audit, revocation).

opencode side (managed config, ADR-0011):
    "provider": {
      "fabagent": {
        "npm": "@ai-sdk/openai-compatible",
        "options": { "baseURL": "https://<server>/v1", "apiKey": "{env:FABAGENT_TOKEN}" }
      }
    }
"""

import hashlib
import json
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import select

from api.auth import require_manager
from api.deps import get_persona_gateway
from core.security import decrypt
from database import get_session
from models import AgentConfig, AuditLog, Personnel, ProviderKey, User
from services.agent_runtime import detect_provider
from services.gateway_auth import PersonaPrincipal, create_persona_token
from services.provider_service import get_provider_models

router = APIRouter(tags=["gateway"])

# Upstream base URLs by provider when the ProviderKey row has no explicit base_url.
_DEFAULT_UPSTREAM = {
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "mistral": "https://api.mistral.ai/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
}

# Faz 4: raw prompt/response retention becomes a per-company setting (ADR-0004).
_STORE_PROMPT_PREVIEW_CHARS = 2000


# Identity: get_persona_gateway lives in api/deps.py (shared with api/workstation.py).


# ── Upstream resolution ───────────────────────────────────────────────────────


def _resolve_upstream(model: str) -> tuple[str, str]:
    """
    Return (base_url, api_key) for the org's configured upstream that serves
    `model`. The org enters its own OpenAI-compatible endpoint as the
    ProviderKey.base_url for the matching provider (ADR-0004).
    """
    provider = detect_provider(model)
    with get_session() as session:
        row = session.exec(
            select(ProviderKey).where(
                ProviderKey.provider == provider,
                ProviderKey.status == "active",
            )
        ).first()
    if not row:
        raise HTTPException(
            status_code=502,
            detail=f"'{provider}' için aktif upstream yapılandırılmamış "
            f"(Ayarlar → AI Sağlayıcılar).",
        )
    base_url = (row.base_url or _DEFAULT_UPSTREAM.get(provider) or "").rstrip("/")
    if not base_url:
        raise HTTPException(
            status_code=502, detail=f"'{provider}' için base_url çözümlenemedi"
        )
    return base_url, decrypt(row.encrypted_key)


# ── Audit ─────────────────────────────────────────────────────────────────────


def _audit_gateway_call(
    principal: PersonaPrincipal,
    model: str,
    body: dict,
    *,
    status: int,
    tokens_in: int | None,
    tokens_out: int | None,
    latency_ms: int,
    streamed: bool,
) -> None:
    """
    Faz 0: write a plain AuditLog row.
    TODO(ADR-0006): route through services.audit_chain for hash-chained,
    tamper-evident records and the append-only /audit/ingest path.
    """
    messages = body.get("messages") or []
    prompt_text = json.dumps(messages, ensure_ascii=False)
    details = {
        "model": model,
        "streamed": streamed,
        "upstream_status": status,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
        "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
        "prompt_preview": prompt_text[:_STORE_PROMPT_PREVIEW_CHARS],
    }
    with get_session() as session:
        session.add(
            AuditLog(
                company_id=principal.company_id,
                user_id=None,
                action="gateway_call",
                entity_type="persona",
                entity_id=principal.persona_id,
                entity_name=model,
                details_json=json.dumps(details, ensure_ascii=False),
                created_at=datetime.utcnow(),
            )
        )
        session.commit()


# ── OpenAI-compatible surface ─────────────────────────────────────────────────


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request, principal: PersonaPrincipal = Depends(get_persona_gateway)
):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz JSON gövde")

    model = body.get("model")
    if not model:
        raise HTTPException(status_code=422, detail="'model' alanı gerekli")

    # TODO(ADR-0005): model allow-list check for this persona/company.
    # TODO(Faz 2): per-persona token quota + rate limit.

    base_url, api_key = _resolve_upstream(model)
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    stream = bool(body.get("stream"))
    t0 = time.monotonic()

    if not stream:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=body, headers=headers)
        latency_ms = round((time.monotonic() - t0) * 1000)
        data = resp.json() if resp.content else {}
        usage = data.get("usage") or {}
        _audit_gateway_call(
            principal,
            model,
            body,
            status=resp.status_code,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            streamed=False,
        )
        return data

    # Streaming passthrough. Token usage is only known at the end of the SSE
    # stream (if the upstream includes a usage chunk); Faz 1 will parse it.
    # Long read window for slow token streams; connect/write stay bounded.
    stream_timeout = httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0)

    async def _proxy_stream():
        async with httpx.AsyncClient(timeout=stream_timeout) as client:
            async with client.stream(
                "POST", url, json=body, headers=headers
            ) as upstream:
                async for chunk in upstream.aiter_raw():
                    yield chunk
        latency_ms = round((time.monotonic() - t0) * 1000)
        _audit_gateway_call(
            principal,
            model,
            body,
            status=200,
            tokens_in=None,
            tokens_out=None,  # TODO(Faz 1): parse final usage chunk
            latency_ms=latency_ms,
            streamed=True,
        )

    return StreamingResponse(_proxy_stream(), media_type="text/event-stream")


@router.get("/v1/models")
def list_models(principal: PersonaPrincipal = Depends(get_persona_gateway)):
    """OpenAI-compatible model list, aggregated across the org's active upstreams."""
    with get_session() as session:
        active = session.exec(
            select(ProviderKey).where(ProviderKey.status == "active")
        ).all()
        out = []
        for row in active:
            plain_key = decrypt(row.encrypted_key)
            for m in get_provider_models(
                row.provider, plain_key, base_url=row.base_url
            ):
                # TODO(ADR-0005): filter by this persona/company model allow-list.
                out.append({"id": m["id"], "object": "model", "owned_by": row.provider})
    return {"object": "list", "data": out}


# ── Persona token minting (Faz 0 — manager only) ─────────────────────────────


@router.post("/gateway/persona-token", status_code=201)
def mint_persona_token(personnel_id: str, _: User = Depends(require_manager)):
    """
    Faz 0 helper: mint a short-lived gateway token for an agent persona so a
    developer can point opencode at the gateway.
    TODO(ADR-0007): replace with `3pa login` against an IdP + refresh + revocation.
    """
    with get_session() as session:
        person = session.get(Personnel, personnel_id)
        if not person:
            raise HTTPException(status_code=404, detail="Personel bulunamadı")
        cfg = session.exec(
            select(AgentConfig).where(AgentConfig.personnel_id == personnel_id)
        ).first()
        if not cfg:
            raise HTTPException(
                status_code=400, detail="Bu personelin ajan yapılandırması yok"
            )
    token = create_persona_token(
        persona_id=person.id,
        company_id=person.company_id,
        scope=None,
    )
    return {"token": token, "token_type": "bearer", "persona_id": person.id}
