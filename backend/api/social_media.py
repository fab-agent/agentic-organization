"""Social media credential management + publish endpoints."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user, require_manager
from core.security import decrypt, encrypt
from database import get_session
from models import AppConfig, User

logger = logging.getLogger("app")
router = APIRouter(prefix="/social-media", tags=["social-media"])

# AppConfig keys
_IG_USER_ID  = "sm_ig_user_id"
_IG_TOKEN    = "sm_ig_access_token_enc"
_WA_PHONE_ID = "sm_wa_phone_number_id"
_WA_TOKEN    = "sm_wa_access_token_enc"
_WA_DEFAULT_TO = "sm_wa_default_to"


def _get(session, key: str) -> Optional[str]:
    row = session.get(AppConfig, key)
    return row.value if row else None


def _set(session, key: str, value: str) -> None:
    existing = session.get(AppConfig, key)
    if existing:
        existing.value = value
        session.add(existing)
    else:
        session.add(AppConfig(key=key, value=value))


# ── Schemas ───────────────────────────────────────────────────────────────────

class SocialConfig(BaseModel):
    ig_user_id: Optional[str] = None
    ig_access_token: Optional[str] = None       # plain on write
    wa_phone_number_id: Optional[str] = None
    wa_access_token: Optional[str] = None        # plain on write
    wa_default_to: Optional[str] = None          # default WhatsApp recipient


class SocialConfigResponse(BaseModel):
    instagram_configured: bool
    ig_user_id: Optional[str] = None
    whatsapp_configured: bool
    wa_phone_number_id: Optional[str] = None
    wa_default_to: Optional[str] = None


class InstagramPostRequest(BaseModel):
    image_url: str
    caption: str


class WhatsAppMessageRequest(BaseModel):
    message: str
    to: Optional[str] = None   # overrides default_to if provided


# ── Config endpoints ───────────────────────────────────────────────────────────

@router.get("/config", response_model=SocialConfigResponse)
def get_social_config(_: User = Depends(get_current_user)):
    with get_session() as session:
        ig_user_id = _get(session, _IG_USER_ID)
        ig_token   = _get(session, _IG_TOKEN)
        wa_phone   = _get(session, _WA_PHONE_ID)
        wa_token   = _get(session, _WA_TOKEN)
        wa_default = _get(session, _WA_DEFAULT_TO)
    return SocialConfigResponse(
        instagram_configured=bool(ig_user_id and ig_token),
        ig_user_id=ig_user_id,
        whatsapp_configured=bool(wa_phone and wa_token),
        wa_phone_number_id=wa_phone,
        wa_default_to=wa_default,
    )


@router.put("/config")
def save_social_config(body: SocialConfig, _: User = Depends(require_manager)):
    with get_session() as session:
        if body.ig_user_id is not None:
            _set(session, _IG_USER_ID, body.ig_user_id)
        if body.ig_access_token:
            _set(session, _IG_TOKEN, encrypt(body.ig_access_token))
        if body.wa_phone_number_id is not None:
            _set(session, _WA_PHONE_ID, body.wa_phone_number_id)
        if body.wa_access_token:
            _set(session, _WA_TOKEN, encrypt(body.wa_access_token))
        if body.wa_default_to is not None:
            _set(session, _WA_DEFAULT_TO, body.wa_default_to)
        session.commit()
    return {"ok": True}


@router.delete("/config", status_code=204)
def delete_social_config(_: User = Depends(require_manager)):
    keys = [_IG_USER_ID, _IG_TOKEN, _WA_PHONE_ID, _WA_TOKEN, _WA_DEFAULT_TO]
    with get_session() as session:
        for k in keys:
            row = session.get(AppConfig, k)
            if row:
                session.delete(row)
        session.commit()


# ── Publish endpoints ─────────────────────────────────────────────────────────

@router.post("/instagram/post")
async def instagram_post(body: InstagramPostRequest, _: User = Depends(get_current_user)):
    """Publish a photo post to the configured Instagram Business account."""
    with get_session() as session:
        ig_user_id = _get(session, _IG_USER_ID)
        ig_token_enc = _get(session, _IG_TOKEN)

    if not ig_user_id or not ig_token_enc:
        raise HTTPException(status_code=422, detail="Instagram yapılandırılmamış.")

    from services.social_media import instagram_post_photo
    try:
        result = await instagram_post_photo(
            ig_user_id=ig_user_id,
            access_token=decrypt(ig_token_enc),
            image_url=body.image_url,
            caption=body.caption,
        )
        logger.info("Instagram post published", extra={"extra": {"media_id": result.get("id")}})
        return result
    except Exception as e:
        logger.error("Instagram post failed", extra={"extra": {"error": str(e)}})
        raise HTTPException(status_code=502, detail=f"Instagram hatası: {e}")


@router.post("/whatsapp/send")
async def whatsapp_send(body: WhatsAppMessageRequest, _: User = Depends(get_current_user)):
    """Send a WhatsApp message via Meta Cloud API."""
    with get_session() as session:
        wa_phone = _get(session, _WA_PHONE_ID)
        wa_token_enc = _get(session, _WA_TOKEN)
        wa_default = _get(session, _WA_DEFAULT_TO)

    if not wa_phone or not wa_token_enc:
        raise HTTPException(status_code=422, detail="WhatsApp yapılandırılmamış.")

    to = body.to or wa_default
    if not to:
        raise HTTPException(status_code=422, detail="Alıcı numarası belirtilmemiş.")

    from services.social_media import whatsapp_send_message
    try:
        result = await whatsapp_send_message(
            phone_number_id=wa_phone,
            access_token=decrypt(wa_token_enc),
            to=to,
            message=body.message,
        )
        logger.info("WhatsApp message sent", extra={"extra": {"to": to}})
        return result
    except Exception as e:
        logger.error("WhatsApp send failed", extra={"extra": {"error": str(e)}})
        raise HTTPException(status_code=502, detail=f"WhatsApp hatası: {e}")
