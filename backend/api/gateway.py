"""
Workstation LLM Gateway — OpenAI-compatible proxy (ADR-0004).

All model traffic from workstation agents (`3pa` → opencode) goes through here so
that, regardless of what the client does:
  - the organisation's own OpenAI-compatible upstream is used (BYO endpoint),
  - every call is written to the tamper-evident audit chain (ADR-0006),
  - the model allow-list / per-persona rate limit / token quota are enforced
    (`services.gateway_limits`, ADR-0004).
  - `POST /policy/decide` serves the workstation plugin (ADR-0005).

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

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from api.auth import require_manager
from api.deps import get_persona_gateway
from core.security import decrypt
from database import get_session
from models import AgentConfig, Personnel, ProviderKey, User
from services import audit_chain, gateway_limits
from services.agent_runtime import detect_provider
from services.gateway_auth import PersonaPrincipal, create_persona_token
from services.policy_engine import PolicyDecisionRequest, audit_decision, decide
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
    """Record the call into the tamper-evident audit chain (ADR-0006)."""
    messages = body.get("messages") or []
    prompt_text = json.dumps(messages, ensure_ascii=False)
    audit_chain.record(
        actor_type="agent",
        actor_id=principal.persona_id,
        company_id=principal.company_id,
        action="gateway_call",
        target=model,
        reason=f"upstream {status}",
        payload={
            "model": model,
            "streamed": streamed,
            "upstream_status": status,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
            "prompt_preview": prompt_text[:_STORE_PROMPT_PREVIEW_CHARS],
        },
    )


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

    # Guardrails (ADR-0004): model allow-list, per-persona rate limit + token quota.
    with get_session() as session:
        agent_cfg = session.exec(
            select(AgentConfig).where(AgentConfig.personnel_id == principal.persona_id)
        ).first()
    gateway_limits.preflight(
        principal.persona_id,
        principal.company_id,
        model,
        agent_cfg.model if agent_cfg else None,
    )

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
        gateway_limits.record_usage(
            principal.persona_id,
            principal.company_id,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
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
            tokens_out=None,  # TODO: parse the final usage chunk of the SSE stream
            latency_ms=latency_ms,
            streamed=True,
        )
        gateway_limits.record_usage(principal.persona_id, principal.company_id, 0, 0)

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


# ── Policy decision (workstation plugin → here, ADR-0005) ────────────────────


class PolicyQuery(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)
    provenance: str = "trusted"  # "trusted" | "untrusted" (ADR-0010)
    session_ref: str | None = None


@router.post("/policy/decide")
def policy_decide(
    query: PolicyQuery, principal: PersonaPrincipal = Depends(get_persona_gateway)
):
    """
    Called by the opencode org plugin in `tool.execute.before`. Returns
    `{effect, reason, enforced, mode}`. The plugin blocks the call only when
    `enforced` is true. The decision is written to the audit either way.
    """
    req = PolicyDecisionRequest(
        tool=query.tool,
        args=query.args,
        provenance=query.provenance,
        source="workstation",
        persona_id=principal.persona_id,
        company_id=principal.company_id,
        session_ref=query.session_ref,
    )
    decision = decide(req)
    audit_decision(req, decision)
    return decision.as_dict()


@router.get("/gateway/usage")
def gateway_usage(personnel_id: str, _: User = Depends(require_manager)):
    """Today + this-month token/request counters for one persona (ADR-0004)."""
    from datetime import datetime

    from models import GatewayUsage

    day = datetime.utcnow().strftime("%Y-%m-%d")
    month = datetime.utcnow().strftime("%Y-%m")
    with get_session() as session:
        rows = {
            r.period: r
            for r in session.exec(
                select(GatewayUsage).where(
                    GatewayUsage.persona_id == personnel_id,
                    GatewayUsage.period.in_([day, month]),
                )
            ).all()
        }

    def _fmt(r):
        return (
            {
                "requests": r.requests,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
            }
            if r
            else {"requests": 0, "tokens_in": 0, "tokens_out": 0}
        )

    return {
        "persona_id": personnel_id,
        "day": _fmt(rows.get(day)),
        "month": _fmt(rows.get(month)),
    }


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
