"""
Onboarding API
──────────────
POST /onboarding/search     → DDG araması, şirket bağlamı döndür
POST /onboarding/chat       → SSE streaming chat (multi-turn)
POST /onboarding/generate   → Yapı JSON'u üret
POST /onboarding/create     → Toplu entity oluştur
GET  /onboarding/status/{company_id} → ai_onboarded durumu
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import update

from api.auth import get_current_user
from database import get_session
from models import Company, User
from services import authz
from services.onboarding_agent import (
    _get_best_key,
    build_onboarding_system,
    create_org_from_structure,
    generate_org_structure,
    get_onboarding_session,
    save_onboarding_session,
    search_company,
    stream_onboarding_chat,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _require_setup(user: User, company_id: str | None) -> None:
    """Company setup (and the LLM spend it triggers) is founder/executive work.

    With a company: company-wide founder/executive of *that* company (404 for
    outsiders). Without one: founder/executive of some company.
    """
    with get_session() as session:
        if company_id:
            authz.require_role(
                session, user.id, company_id, authz.FINAL, company_wide=True
            )
        elif not any(
            m.role in authz.FINAL and m.scope_id is None
            for m in authz.memberships_all(session, user.id)
        ):
            raise HTTPException(403, "Kurulum için kurucu/yönetici yetkisi gerekir")


# ── Request models ─────────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    company_name: str
    company_id: str | None = None


class ChatRequest(BaseModel):
    company_name: str
    search_context: str
    messages: list[dict]  # [{role: user|assistant, content: str}]
    company_id: str | None = None
    locale: str = "tr"


class GenerateRequest(BaseModel):
    company_name: str
    search_context: str
    messages: list[dict]
    company_id: str | None = None
    locale: str = "tr"


class CreateRequest(BaseModel):
    company_id: str
    structure: dict


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/status/{company_id}")
def onboarding_status(company_id: str, user: User = Depends(get_current_user)):
    _require_setup(user, company_id)
    with get_session() as session:
        company = session.get(Company, company_id)
        if not company:
            raise HTTPException(404, "Şirket bulunamadı")
        saved = get_onboarding_session(company_id)
        return {
            "company_id": company_id,
            "ai_onboarded": company.ai_onboarded,
            "session": saved,  # None if no in-progress session
        }


@router.post("/search")
async def onboarding_search(
    body: SearchRequest, user: User = Depends(get_current_user)
):
    _require_setup(user, body.company_id)
    """Run DDG web search and return context string. Saves progress to DB."""
    context = search_company(body.company_name)
    key_info = _get_best_key()
    if not key_info:
        raise HTTPException(
            503,
            "Aktif AI sağlayıcı anahtarı bulunamadı. Lütfen Ayarlar → AI Sağlayıcılar bölümünden bir anahtar ekleyin.",
        )
    provider, model, _ = key_info
    if body.company_id:
        save_onboarding_session(body.company_id, phase="chat", search_context=context)
    return {
        "context": context,
        "provider": provider,
        "model": model,
    }


@router.post("/chat")
async def onboarding_chat(body: ChatRequest, user: User = Depends(get_current_user)):
    _require_setup(user, body.company_id)
    """Stream onboarding assistant response via SSE."""
    key_info = _get_best_key()
    if not key_info:
        raise HTTPException(503, "Aktif AI sağlayıcı anahtarı bulunamadı.")
    provider, model, api_key = key_info

    # Build messages with system prompt and search context prepended
    system_content = build_onboarding_system(body.locale)
    if body.search_context:
        label = (
            "Web research results"
            if body.locale == "en"
            else "Web araştırması sonuçları"
        )
        system_content += f"\n\n{label} ({body.company_name}):\n{body.search_context}"

    full_messages = [{"role": "system", "content": system_content}] + body.messages

    async def event_generator():
        try:
            full_text = []
            async for chunk in stream_onboarding_chat(
                full_messages, provider, model, api_key
            ):
                full_text.append(chunk)
                yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
            text = "".join(full_text)
            ready = "<READY_TO_GENERATE/>" in text
            # Save conversation after each AI reply
            if body.company_id:
                assistant_msg = {
                    "role": "assistant",
                    "content": text.replace("<READY_TO_GENERATE/>", "").strip(),
                }
                all_msgs = body.messages + [assistant_msg]
                save_onboarding_session(
                    body.company_id,
                    phase="chat",
                    search_context=body.search_context,
                    messages=all_msgs,
                )
            yield f"data: {json.dumps({'type': 'done', 'ready': ready})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/generate")
async def onboarding_generate(
    body: GenerateRequest, user: User = Depends(get_current_user)
):
    _require_setup(user, body.company_id)
    """Generate the org structure JSON from the conversation."""
    key_info = _get_best_key()
    if not key_info:
        raise HTTPException(503, "Aktif AI sağlayıcı anahtarı bulunamadı.")
    provider, model, api_key = key_info

    try:
        structure = await generate_org_structure(
            body.company_name,
            body.messages,
            provider,
            model,
            api_key,
            locale=body.locale,
        )
        if body.company_id:
            save_onboarding_session(
                body.company_id,
                phase="preview",
                structure=structure,
            )
        return {"structure": structure}
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"AI geçersiz JSON üretiyor: {e}")
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/create")
def onboarding_create(body: CreateRequest, user: User = Depends(get_current_user)):
    """Bulk-create all entities from the confirmed structure."""
    _require_setup(user, body.company_id)
    with get_session() as session:
        company = session.get(Company, body.company_id)
        if not company:
            raise HTTPException(404, "Şirket bulunamadı")
        # Claim the one-time setup atomically: two concurrent calls cannot both win.
        res = session.exec(
            update(Company)
            .where(Company.id == body.company_id, Company.ai_onboarded == False)  # noqa: E712
            .values(ai_onboarded=True)
        )
        session.commit()
        if res.rowcount != 1:
            raise HTTPException(409, "Bu şirket zaten AI onboarding ile kuruldu.")

    key_info = _get_best_key()
    fallback_model = key_info[1] if key_info else "qwen-plus"
    try:
        summary = create_org_from_structure(
            body.company_id, body.structure, fallback_model=fallback_model
        )
        return {"success": True, "summary": summary}
    except Exception as e:
        # Release the claim so a failed setup can be retried.
        with get_session() as session:
            session.exec(
                update(Company)
                .where(Company.id == body.company_id)
                .values(ai_onboarded=False)
            )
            session.commit()
        raise HTTPException(500, f"Oluşturma hatası: {e}")
