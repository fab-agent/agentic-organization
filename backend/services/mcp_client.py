"""
MCP (Model Context Protocol) client — supports SSE and HTTP transports.
stdio transport is deferred to a future phase.
"""

import json
from typing import Any

import httpx


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


async def call_mcp_sse_tool(
    url: str, auth_type: str, auth_value: str | None, tool_name: str, args: dict
) -> Any:
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


async def execute_builtin(
    function_name: str,
    args: dict,
    session_id: str | None = None,
    agent_id: str | None = None,
) -> Any:
    """Execute a built-in capability by name."""
    if function_name == "web_search":
        query = args.get("query", "")
        url = f"https://api.duckduckgo.com/?format=json&no_html=1&q={query}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            data = resp.json()
        topics = data.get("RelatedTopics", [])[:5]
        results = [
            t.get("Text", "") for t in topics if isinstance(t, dict) and t.get("Text")
        ]
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

    if function_name == "journal_write":
        return await _journal_write(args, session_id, agent_id)

    if function_name == "db_query":
        return await _db_query(args)

    if function_name == "function":
        return _run_function(args)

    return f"[Built-in '{function_name}' not implemented]"


async def _delegate_to_agent(
    args: dict, session_id: str | None, from_agent_id: str | None
) -> str:
    """Create an A2A delegation request and return status."""
    if not session_id or not from_agent_id:
        return "[A2A delegation error: missing session_id or agent_id]"

    to_slug = args.get("to_agent_slug", "")
    pre_id = args.get("_to_agent_id", "")
    task = args.get("task", "")
    context = args.get("context")

    if not (to_slug or pre_id) or not task:
        return "[A2A delegation error: to_agent_slug (or pre-configured target) and task are required]"

    from sqlmodel import select

    from database import get_session as _get_session
    from models import A2ARequest, AgentConfig, Personnel

    with _get_session() as db:
        if pre_id:
            target = db.get(Personnel, pre_id)
        else:
            target = db.exec(select(Personnel).where(Personnel.slug == to_slug)).first()
        if not target:
            lookup = pre_id or to_slug
            return f"[A2A delegation error: agent '{lookup}' not found]"

        # Verify target is an agent
        cfg = db.exec(
            select(AgentConfig).where(AgentConfig.personnel_id == target.id)
        ).first()
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
    from core.security import decrypt
    from database import get_session as _gs
    from models import AppConfig
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
    from core.security import decrypt
    from database import get_session as _gs
    from models import AppConfig
    from services.social_media import whatsapp_send_message

    message = args.get("message", "")
    to = args.get("to", "")
    if not message:
        return "[whatsapp_send] message gerekli"

    with _gs() as db:
        phone_row = db.get(AppConfig, "sm_wa_phone_number_id")
        token_row = db.get(AppConfig, "sm_wa_access_token_enc")
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


async def _journal_write(
    args: dict, session_id: str | None, agent_id: str | None
) -> str:
    """Builtin: agent writes a work log entry to its own journal."""
    content = args.get("content", "").strip()
    title = args.get("title", "").strip() or None

    if not content:
        return "[journal_write] content gerekli"
    if not agent_id:
        return "[journal_write] agent_id bulunamadı"

    from database import get_session as _gs
    from models import WorkJournalEntry

    with _gs() as db:
        entry = WorkJournalEntry(
            personnel_id=agent_id,
            session_id=session_id,
            author="agent",
            title=title,
            content=content,
        )
        db.add(entry)
        db.commit()

    title_part = f'"{title}"' if title else "günlük kaydı"
    return f"✅ Günlüğe yazıldı: {title_part}"


async def _db_query(args: dict) -> str:
    """Builtin: execute a SELECT query against a configured database connection."""
    db_id = args.get("db_id", "")
    sql = args.get("sql", "").strip()

    if not db_id:
        return "[db_query] db_id gerekli — skill config'inde database_id belirtin"
    if not sql:
        return "[db_query] sql gerekli"

    from core.security import decrypt
    from database import get_session as _gs
    from models import DatabaseConnection
    from services.database_service import execute_query

    with _gs() as db:
        row = db.get(DatabaseConnection, db_id)
        if not row:
            return f"[db_query] '{db_id}' ID'li veritabanı bulunamadı"
        dsn = decrypt(row.encrypted_dsn)
        db_type = row.db_type

    try:
        result = execute_query(dsn, db_type, sql, limit=100)
        cols = result["columns"]
        rows = result["rows"]
        if not rows:
            return "Sorgu sonuç döndürmedi."
        # Format as markdown table
        header = " | ".join(cols)
        sep = " | ".join(["---"] * len(cols))
        body_lines = [" | ".join(str(v) for v in row) for row in rows[:50]]
        table = "\n".join([header, sep] + body_lines)
        note = f"\n\n_{len(rows)} satır döndü" + (
            "_" if len(rows) < 100 else " (ilk 100 gösteriliyor)_"
        )
        return table + note
    except ValueError as e:
        return f"[db_query] Güvenlik hatası: {e}"
    except Exception as e:
        return f"[db_query] Sorgu hatası: {e}"


def _run_function(args: dict) -> str:
    """
    Builtin: execute user-defined Python code stored in skill config.
    The code must define a function named `run(args: dict) -> str`.
    Runs in a restricted namespace with a 5-second wall-clock timeout.
    """
    code = args.get("__code__", "")  # injected from skill config at call time
    if not code:
        return "[function] Çalıştırılacak kod bulunamadı (skill config'inde 'code' alanı gerekli)"

    import threading

    result_holder: list = []
    error_holder: list = []

    _SAFE_BUILTINS = {
        "print": print,
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "sorted": sorted,
        "sum": sum,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "isinstance": isinstance,
        "type": type,
        "repr": repr,
        "json": __import__("json"),
    }

    def _exec():
        try:
            namespace: dict = {"__builtins__": _SAFE_BUILTINS}
            exec(compile(code, "<skill>", "exec"), namespace)
            fn = namespace.get("run")
            if not callable(fn):
                error_holder.append("Kod 'run(args)' fonksiyonu tanımlamalı")
                return
            result = fn({k: v for k, v in args.items() if k != "__code__"})
            result_holder.append(str(result) if result is not None else "")
        except Exception as e:
            error_holder.append(f"Çalışma hatası: {e}")

    t = threading.Thread(target=_exec, daemon=True)
    t.start()
    t.join(timeout=5)

    if t.is_alive():
        return "[function] Zaman aşımı (5 saniye)"
    if error_holder:
        return f"[function] {error_holder[0]}"
    return result_holder[0] if result_holder else ""
