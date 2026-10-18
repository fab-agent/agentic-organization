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

import asyncio
import hashlib
import json
import re
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
from services.gateway_auth import PersonaPrincipal, create_persona_token, run_info
from services.model_routing import ModelRoutingError, resolve_model
from services.policy_engine import PolicyDecisionRequest, audit_decision, decide
from services.provider_service import get_provider_models, is_custom_provider

router = APIRouter(tags=["gateway"])

# Faz 4: raw prompt/response retention becomes a per-company setting (ADR-0004).
_STORE_PROMPT_PREVIEW_CHARS = 2000


# Identity: get_persona_gateway lives in api/deps.py (shared with api/workstation.py).


# ── Upstream resolution ───────────────────────────────────────────────────────


def _resolve_upstream(model: str, provider: str | None = None) -> tuple[str, str, str]:
    """
    Return (base_url, api_key, upstream_model) for the org's configured upstream
    that serves `model` (services.model_routing, ADR-0004 / ADR-0016). A
    `<provider>/<model>` reference is resolved to that provider and the prefix is
    stripped before the request is forwarded.
    """
    try:
        resolved = resolve_model(model, provider)
    except ModelRoutingError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not resolved.base_url:
        raise HTTPException(
            status_code=502,
            detail=f"'{resolved.provider}' için base_url çözümlenemedi",
        )
    return resolved.base_url, resolved.api_key, resolved.model


# ── Audit ─────────────────────────────────────────────────────────────────────


_FINISH_RE = re.compile(r"[a-z_]{1,32}")


def _finish_info(obj: object) -> tuple[str | None, bool]:
    """(finish_reason, has_output) from one chat completion / stream chunk.

    Only a short lowercase token is kept as finish_reason (provider text is never
    stored); has_output is True when the choice carries content or tool calls.
    """
    if not isinstance(obj, dict):
        return None, False
    choices = obj.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(choice, dict):
        return None, False
    fr = choice.get("finish_reason")
    fr = fr if isinstance(fr, str) and _FINISH_RE.fullmatch(fr) else None
    part = choice.get("message") or choice.get("delta") or {}
    has = bool(
        isinstance(part, dict) and (part.get("content") or part.get("tool_calls"))
    )
    return fr, has


def _sse_info(line: bytes) -> tuple[str | None, bool, bool]:
    """(finish_reason, has_output, is_done) for one SSE line."""
    s_ = line.strip()
    if not s_.startswith(b"data:"):
        return None, False, False
    payload = s_[5:].strip()
    if payload == b"[DONE]":
        return None, False, True
    try:
        obj = json.loads(payload)
    except (ValueError, TypeError):
        return None, False, False
    fr, has = _finish_info(obj)
    return fr, has, False


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
    failure: str | None = None,
    finish_reason: str | None = None,
    has_output: bool | None = None,
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
        reason=f"upstream {status}" if not failure else f"failure {failure}",
        payload={
            "model": model,
            "streamed": streamed,
            "upstream_status": status,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            # timeout | transport | parse | cut | client_closed (ADR-0023 follow-up 0)
            "failure": failure,
            "finish_reason": finish_reason,
            "has_output": has_output,
            "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
            "prompt_preview": prompt_text[:_STORE_PROMPT_PREVIEW_CHARS],
            **({"run": run_info(principal)} if principal.run_id else {}),
        },
    )


# ── OpenAI-compatible surface ─────────────────────────────────────────────────


def _sse_usage(line: bytes) -> dict | None:
    """
    Pull an OpenAI-style `usage` object out of one SSE `data:` line, or None.
    Providers put it on the last chunk (choices == []) once `stream_options`
    asks for it; some repeat it on every chunk — the caller keeps the last.
    """
    s = line.strip()
    if not s.startswith(b"data:"):
        return None
    payload = s[5:].strip()
    if not payload or payload == b"[DONE]":
        return None
    try:
        obj = json.loads(payload)
    except (ValueError, TypeError):
        return None
    usage = obj.get("usage") if isinstance(obj, dict) else None
    if isinstance(usage, dict) and usage.get("total_tokens") is not None:
        return usage
    return None


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

    # The persona's own model goes to its configured provider (AgentConfig.provider).
    own_provider = (
        agent_cfg.provider if agent_cfg and agent_cfg.model == model else None
    )
    base_url, api_key, upstream_model = _resolve_upstream(model, own_provider)
    if upstream_model != model:
        body = {**body, "model": upstream_model}
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    stream = bool(body.get("stream"))
    t0 = time.monotonic()

    if not stream:
        failure: str | None = None
        resp = None
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException:
            failure = "timeout"
        except httpx.HTTPError:
            failure = "transport"
        data: dict = {}
        if resp is not None:
            try:
                data = resp.json() if resp.content else {}
                if not isinstance(data, dict):
                    raise ValueError("not an object")
            except ValueError:
                failure, data = "parse", {}
        latency_ms = round((time.monotonic() - t0) * 1000)
        usage = data.get("usage") or {}
        finish_reason, has_output = _finish_info(data)
        _audit_gateway_call(
            principal,
            model,
            body,
            status=resp.status_code if resp is not None else 0,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            streamed=False,
            failure=failure,
            finish_reason=finish_reason,
            has_output=has_output if resp is not None and not failure else None,
        )
        if failure:
            raise HTTPException(
                status_code=504 if failure == "timeout" else 502,
                detail=f"Upstream failure: {failure}",
            )
        gateway_limits.record_usage(
            principal.persona_id,
            principal.company_id,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )
        return data

    # Streaming passthrough. Token usage is only in the SSE stream's final chunk,
    # and only when the upstream is asked for it — inject `stream_options` when
    # the client did not (the extra usage-only chunk flows through to the client,
    # which openai-compatible SDKs expect). We tee the raw chunks through a line
    # buffer and pull `usage` out for the audit + quota counters (ADR-0004).
    upstream_body = body
    if "stream_options" not in body:
        upstream_body = {**body, "stream_options": {"include_usage": True}}

    # Long read window for slow token streams; connect/write stay bounded.
    stream_timeout = httpx.Timeout(connect=10.0, read=900.0, write=30.0, pool=10.0)

    async def _proxy_stream():
        usage: dict = {}
        line_buf = b""
        upstream_status = 0
        failure: str | None = None
        finish_reason: str | None = None
        has_output = False
        done = False

        def _scan(line: bytes) -> None:
            nonlocal usage, finish_reason, has_output, done
            found = _sse_usage(line)
            if found:
                usage = found
            fr, has, is_done = _sse_info(line)
            finish_reason = fr or finish_reason
            has_output = has_output or has
            done = done or is_done

        try:
            async with httpx.AsyncClient(timeout=stream_timeout) as client:
                async with client.stream(
                    "POST", url, json=upstream_body, headers=headers
                ) as upstream:
                    upstream_status = upstream.status_code
                    async for chunk in upstream.aiter_raw():
                        yield chunk
                        line_buf += chunk
                        while b"\n" in line_buf:
                            line, line_buf = line_buf.split(b"\n", 1)
                            _scan(line)
            _scan(line_buf)
            if upstream_status < 400 and not done and finish_reason is None:
                failure = "cut"
        except httpx.TimeoutException:
            failure = "timeout"
        except httpx.HTTPError:
            failure = "transport"
        except (asyncio.CancelledError, GeneratorExit):
            failure = "client_closed"
            raise
        finally:
            latency_ms = round((time.monotonic() - t0) * 1000)
            tokens_in = usage.get("prompt_tokens")
            tokens_out = usage.get("completion_tokens")
            _audit_gateway_call(
                principal,
                model,
                body,
                status=upstream_status,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                streamed=True,
                failure=failure,
                finish_reason=finish_reason,
                has_output=has_output,
            )
            gateway_limits.record_usage(
                principal.persona_id, principal.company_id, tokens_in, tokens_out
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
                # Custom endpoints are listed as `<provider>/<model>` so two
                # endpoints serving the same model id stay distinguishable.
                mid = (
                    f"{row.provider}/{m['id']}"
                    if is_custom_provider(row.provider)
                    else m["id"]
                )
                out.append({"id": mid, "object": "model", "owned_by": row.provider})
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
        run=run_info(principal),
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
