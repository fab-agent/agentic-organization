"""
MCP (Model Context Protocol) client — supports SSE and HTTP transports.
stdio transport is deferred to a future phase.
"""
import json
import asyncio
import httpx
from typing import Any


async def call_http_tool(url: str, method: str, headers: dict, args: dict) -> Any:
    """Call an HTTP-based skill endpoint."""
    async with httpx.AsyncClient(timeout=30) as client:
        if method.upper() == "GET":
            resp = await client.get(url, params=args, headers=headers)
        else:
            resp = await client.post(url, json=args, headers=headers)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return resp.text


async def call_mcp_sse_tool(url: str, auth_type: str, auth_value: str | None, tool_name: str, args: dict) -> Any:
    """
    Call a tool on an MCP server using HTTP transport (JSON-RPC over POST).
    The MCP server must expose a /call endpoint accepting JSON-RPC 2.0.
    """
    headers: dict = {"Content-Type": "application/json"}
    if auth_type == "api_key" and auth_value:
        headers["X-API-Key"] = auth_value
    elif auth_type in ("bearer", "oauth2") and auth_value:
        headers["Authorization"] = f"Bearer {auth_value}"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }

    base_url = url.rstrip("/")
    endpoint = f"{base_url}/call" if not base_url.endswith("/call") else base_url

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(endpoint, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")

    result = data.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list) and content[0].get("type") == "text":
        return content[0]["text"]
    return result


BUILTIN_WEB_SEARCH_URL = "https://api.duckduckgo.com/?format=json&no_html=1&q={query}"


async def execute_builtin(function_name: str, args: dict, session_id: str | None = None, agent_id: str | None = None) -> Any:
    """Execute a built-in capability by name."""
    if function_name == "web_search":
        query = args.get("query", "")
        url = f"https://api.duckduckgo.com/?format=json&no_html=1&q={query}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            data = resp.json()
        topics = data.get("RelatedTopics", [])[:5]
        results = [t.get("Text", "") for t in topics if isinstance(t, dict) and t.get("Text")]
        return "\n".join(results) if results else "No results found."

    if function_name == "text_to_chart":
        return f"[Chart generation placeholder — data: {json.dumps(args)}]"

    if function_name == "code_execution":
        return f"[Code execution deferred — code: {args.get('code', '')[:100]}]"

    if function_name == "delegate_to_agent":
        return await _delegate_to_agent(args, session_id, agent_id)

    if function_name == "instagram_post":
        return await _instagram_post(args)

    if function_name == "whatsapp_send":
        return await _whatsapp_send(args)

    return f"[Built-in '{function_name}' not implemented]"


async def _delegate_to_agent(args: dict, session_id: str | None, from_agent_id: str | None) -> str:
    """Create an A2A delegation request and return status."""
    if not session_id or not from_agent_id:
        return "[A2A delegation error: missing session_id or agent_id]"

    to_slug = args.get("to_agent_slug", "")
    task = args.get("task", "")
    context = args.get("context")

    if not to_slug or not task:
        return "[A2A delegation error: to_agent_slug and task are required]"

    from database import get_session as _get_session
    from models import Personnel, AgentConfig, A2ARequest
    from sqlmodel import select

    with _get_session() as db:
        target = db.exec(select(Personnel).where(Personnel.slug == to_slug)).first()
        if not target:
            return f"[A2A delegation error: agent with slug '{to_slug}' not found]"

        # Verify target is an agent
        cfg = db.exec(select(AgentConfig).where(AgentConfig.personnel_id == target.id)).first()
        if not cfg:
            return f"[A2A delegation error: '{to_slug}' has no agent config]"

        req = A2ARequest(
            from_session_id=session_id,
            from_agent_id=from_agent_id,
            to_agent_id=target.id,
            task=task,
            context=context,
            status="pending_approval",
        )
        # Auto-assign approver
        if cfg.responsible_id:
            req.approver_id = cfg.responsible_id

        db.add(req)
        db.commit()
        db.refresh(req)

        approver = db.get(Personnel, req.approver_id) if req.approver_id else None
        approver_name = approver.name if approver else "sorumlu kişi"

    return (
        f"✅ **Delegasyon talebi oluşturuldu** → `{target.name}` ajanına\n\n"
        f"**Görev**: {task}\n\n"
        f"**Durum**: Onay bekleniyor ({approver_name})\n"
        f"**Talep ID**: `{req.id}`\n\n"
        f"Talep onaylandıktan sonra {target.name} görevi yürütecek ve sonuç geri gelecektir."
    )


async def _instagram_post(args: dict) -> str:
    """Builtin: publish a photo post to the platform's configured Instagram account."""
    from database import get_session as _gs
    from models import AppConfig
    from core.security import decrypt
    from services.social_media import instagram_post_photo

    image_url = args.get("image_url", "")
    caption = args.get("caption", "")
    if not image_url:
        return "[instagram_post] image_url gerekli"
    if not caption:
        return "[instagram_post] caption gerekli"

    with _gs() as db:
        ig_id_row = db.get(AppConfig, "sm_ig_user_id")
        ig_tok_row = db.get(AppConfig, "sm_ig_access_token_enc")

    if not ig_id_row or not ig_tok_row:
        return "[instagram_post] Instagram yapılandırılmamış — Ayarlar > Sosyal Medya'yı doldurun."

    try:
        result = await instagram_post_photo(
            ig_user_id=ig_id_row.value,
            access_token=decrypt(ig_tok_row.value),
            image_url=image_url,
            caption=caption,
        )
        media_id = result.get("id", "?")
        return f"✅ Instagram'a yayınlandı — medya ID: `{media_id}`\nCaption: {caption}"
    except Exception as e:
        return f"[instagram_post] Hata: {e}"


async def _whatsapp_send(args: dict) -> str:
    """Builtin: send a WhatsApp text message via the platform's configured account."""
    from database import get_session as _gs
    from models import AppConfig
    from core.security import decrypt
    from services.social_media import whatsapp_send_message

    message = args.get("message", "")
    to = args.get("to", "")
    if not message:
        return "[whatsapp_send] message gerekli"

    with _gs() as db:
        phone_row   = db.get(AppConfig, "sm_wa_phone_number_id")
        token_row   = db.get(AppConfig, "sm_wa_access_token_enc")
        default_row = db.get(AppConfig, "sm_wa_default_to")

    if not phone_row or not token_row:
        return "[whatsapp_send] WhatsApp yapılandırılmamış — Ayarlar > Sosyal Medya'yı doldurun."

    recipient = to or (default_row.value if default_row else "")
    if not recipient:
        return "[whatsapp_send] Alıcı numarası belirtilmemiş (to parametresi veya varsayılan numara gerekli)."

    try:
        result = await whatsapp_send_message(
            phone_number_id=phone_row.value,
            access_token=decrypt(token_row.value),
            to=recipient,
            message=message,
        )
        msg_id = result.get("messages", [{}])[0].get("id", "?")
        return f"✅ WhatsApp mesajı gönderildi → `{recipient}`\nMesaj ID: `{msg_id}`\nİçerik: {message}"
    except Exception as e:
        return f"[whatsapp_send] Hata: {e}"
