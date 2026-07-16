"""
Telegram Bot Webhook — interactive agent interface.

Commands:
  /start | /ajanlar  → agent selection keyboard
  /degistir          → re-open agent selection
  /durum             → current agent + system status
  /onaylar           → list pending task/A2A approvals
  Any text           → routed to selected agent

Inline buttons:
  select_agent:{personnel_id}  → set active agent
  approve_task:{task_id}       → approve TaskRequest
  reject_task:{task_id}        → reject TaskRequest
  approve_a2a:{a2a_id}         → approve A2ARequest
  reject_a2a:{a2a_id}          → reject A2ARequest
"""

import asyncio
import json
from datetime import datetime

import httpx
from fastapi import APIRouter
from sqlmodel import select

from core.security import decrypt
from database import get_session
from models import (
    A2ARequest,
    AgentConfig,
    AgentSession,
    CompanyMember,
    Personnel,
    TaskRequest,
    TelegramBotState,
    TelegramConfig,
)

router = APIRouter(tags=["telegram-bot"])

_BOT_BASE = "https://api.telegram.org/bot{token}/{method}"


# ── Telegram API helpers ───────────────────────────────────────────────────────


def _tg_url(token: str, method: str) -> str:
    return _BOT_BASE.format(token=token, method=method)


def _send(
    token: str,
    chat_id: str,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str = "HTML",
) -> None:
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        with httpx.Client(timeout=10) as c:
            c.post(_tg_url(token, "sendMessage"), json=payload)
    except Exception:
        pass


def _edit_message(token: str, chat_id: str, message_id: int, text: str) -> None:
    try:
        with httpx.Client(timeout=10) as c:
            c.post(
                _tg_url(token, "editMessageText"),
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
            )
    except Exception:
        pass


def _answer_callback(token: str, callback_query_id: str, text: str = "") -> None:
    try:
        with httpx.Client(timeout=5) as c:
            c.post(
                _tg_url(token, "answerCallbackQuery"),
                json={
                    "callback_query_id": callback_query_id,
                    "text": text,
                },
            )
    except Exception:
        pass


def _split_and_send(
    token: str, chat_id: str, text: str, parse_mode: str = "HTML"
) -> None:
    """Split long messages at 4096-char Telegram limit."""
    limit = 4096
    while text:
        chunk, text = text[:limit], text[limit:]
        _send(token, chat_id, chunk, parse_mode=parse_mode)


# ── Bot config loader ──────────────────────────────────────────────────────────


def _get_bot_token(company_id: str | None = None) -> str | None:
    with get_session() as db:
        q = select(TelegramConfig).where(TelegramConfig.is_active == True)
        if company_id:
            q = q.where(TelegramConfig.company_id == company_id)
        cfg = db.exec(q).first()
        if not cfg:
            cfg = db.exec(
                select(TelegramConfig).where(TelegramConfig.is_active == True)
            ).first()
        if not cfg:
            return None
        return decrypt(cfg.encrypted_token)


def _get_or_create_state(chat_id: str) -> TelegramBotState:
    with get_session() as db:
        state = db.get(TelegramBotState, chat_id)
        if not state:
            # Auto-link to first company
            member = db.exec(select(CompanyMember)).first()
            state = TelegramBotState(
                chat_id=chat_id,
                company_id=member.company_id if member else None,
                updated_at=datetime.utcnow(),
            )
            db.add(state)
            db.commit()
            db.refresh(state)
        return state


def _save_state(state: TelegramBotState) -> None:
    with get_session() as db:
        state.updated_at = datetime.utcnow()
        db.add(state)
        db.commit()


# ── Agent keyboard builder ─────────────────────────────────────────────────────


def _agent_keyboard(company_id: str | None) -> dict:
    with get_session() as db:
        q = (
            select(Personnel, AgentConfig)
            .join(AgentConfig, AgentConfig.personnel_id == Personnel.id)
            .where(Personnel.type == "agent")
            .where(AgentConfig.status == "active")
        )
        if company_id:
            q = q.where(Personnel.company_id == company_id)
        rows = db.exec(q).all()

    buttons = []
    row = []
    for person, cfg in rows:
        row.append({"text": person.name, "callback_data": f"select_agent:{person.id}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    return {"inline_keyboard": buttons}


# ── Pending approvals ──────────────────────────────────────────────────────────


def _pending_approvals_text_and_keyboard(company_id: str | None) -> tuple[str, dict]:
    with get_session() as db:
        tasks = (
            db.exec(
                select(TaskRequest)
                .where(TaskRequest.company_id == company_id)
                .where(TaskRequest.status == "assigned")
                .order_by(TaskRequest.created_at.desc())
                .limit(5)
            ).all()
            if company_id
            else []
        )

        a2as = db.exec(
            select(A2ARequest)
            .where(A2ARequest.status == "pending_approval")
            .order_by(A2ARequest.created_at.desc())
            .limit(5)
        ).all()

    if not tasks and not a2as:
        return "✅ Bekleyen onay yok.", {"inline_keyboard": []}

    lines = ["📋 <b>Bekleyen Onaylar</b>\n"]
    buttons = []

    for t in tasks:
        lines.append(f"📌 <b>[Görev]</b> {t.title}\n<i>{t.body[:100]}...</i>")
        buttons.append(
            [
                {
                    "text": f"✅ Onayla — {t.title[:20]}",
                    "callback_data": f"approve_task:{t.id}",
                },
                {"text": "❌ Reddet", "callback_data": f"reject_task:{t.id}"},
            ]
        )

    for a in a2as:
        lines.append(f"🤝 <b>[A2A]</b> {a.task_title or 'Delegasyon'}")
        buttons.append(
            [
                {
                    "text": f"✅ Onayla — {(a.task_title or 'A2A')[:20]}",
                    "callback_data": f"approve_a2a:{a.id}",
                },
                {"text": "❌ Reddet", "callback_data": f"reject_a2a:{a.id}"},
            ]
        )

    return "\n".join(lines), {"inline_keyboard": buttons}


# ── Agent runner (sync wrapper around async run_session) ──────────────────────


async def _run_agent(session_id: str, message: str) -> str:
    from services.agent_runtime import run_session

    parts = []
    async for event in run_session(session_id, message):
        if event.get("type") == "text":
            parts.append(event["content"])
    return "".join(parts) or "⚠️ Ajanın cevabı boş döndü."


def _ensure_session(state: TelegramBotState) -> str:
    """Get or create an AgentSession for the current agent selection."""
    with get_session() as db:
        # Reuse existing open session
        if state.active_session_id:
            sess = db.get(AgentSession, state.active_session_id)
            if sess and sess.status in ("active", "idle"):
                return state.active_session_id

        # Create new session
        sess = AgentSession(
            personnel_id=state.selected_agent_id,
            title=f"Telegram — {state.selected_agent_name}",
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(sess)
        db.commit()
        db.refresh(sess)
        return sess.id


# ── Update processor ───────────────────────────────────────────────────────────


def process_telegram_update(data: dict) -> None:
    """Synchronous entry point called from BackgroundTasks."""
    asyncio.run(_process_async(data))


async def _process_async(data: dict) -> None:
    token = _get_bot_token()
    if not token:
        return

    # ── Callback query (button press) ─────────────────────────────────────────
    if "callback_query" in data:
        cq = data["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        cq_id = cq["id"]
        cb_data = cq.get("data", "")
        _answer_callback(token, cq_id)

        state = _get_or_create_state(chat_id)

        if cb_data.startswith("select_agent:"):
            agent_id = cb_data.split(":", 1)[1]
            with get_session() as db:
                agent = db.get(Personnel, agent_id)
            if agent:
                state.selected_agent_id = agent_id
                state.selected_agent_name = agent.name
                state.active_session_id = None  # fresh session for new agent
                _save_state(state)
                _send(
                    token,
                    chat_id,
                    f"✅ <b>{agent.name}</b> seçildi.\n\n"
                    f"Mesajını yaz, doğrudan ona iletiyorum.\n"
                    f"<i>Değiştirmek için /degistir</i>",
                )
            return

        if cb_data.startswith("approve_task:"):
            task_id = cb_data.split(":", 1)[1]
            with get_session() as db:
                task = db.get(TaskRequest, task_id)
                if task and task.status == "assigned":
                    task.status = "running"
                    task.updated_at = datetime.utcnow()
                    db.add(task)
                    db.commit()
            _send(token, chat_id, "✅ Görev onaylandı ve çalıştırılıyor...")
            return

        if cb_data.startswith("reject_task:"):
            task_id = cb_data.split(":", 1)[1]
            with get_session() as db:
                task = db.get(TaskRequest, task_id)
                if task:
                    task.status = "rejected"
                    task.updated_at = datetime.utcnow()
                    db.add(task)
                    db.commit()
            _send(token, chat_id, "❌ Görev reddedildi.")
            return

        if cb_data.startswith("approve_a2a:"):
            a2a_id = cb_data.split(":", 1)[1]
            with get_session() as db:
                a2a = db.get(A2ARequest, a2a_id)
                if a2a and a2a.status == "pending_approval":
                    a2a.status = "approved"
                    a2a.updated_at = datetime.utcnow()
                    db.add(a2a)
                    db.commit()
            _send(token, chat_id, "✅ A2A delegasyonu onaylandı.")
            return

        if cb_data.startswith("reject_a2a:"):
            a2a_id = cb_data.split(":", 1)[1]
            with get_session() as db:
                a2a = db.get(A2ARequest, a2a_id)
                if a2a:
                    a2a.status = "rejected"
                    a2a.updated_at = datetime.utcnow()
                    db.add(a2a)
                    db.commit()
            _send(token, chat_id, "❌ A2A delegasyonu reddedildi.")
            return

        return

    # ── Regular message ────────────────────────────────────────────────────────
    if "message" not in data:
        return

    msg = data["message"]
    chat_id = str(msg["chat"]["id"])
    text = msg.get("text", "").strip()
    if not text:
        return

    state = _get_or_create_state(chat_id)

    # Commands
    if text in ("/start", "/ajanlar"):
        keyboard = _agent_keyboard(state.company_id)
        _send(
            token,
            chat_id,
            "🤖 <b>Fabrika Yapay Zeka</b>\n\nHangi ajanla çalışmak istiyorsun?",
            reply_markup=keyboard,
        )
        return

    if text == "/degistir":
        keyboard = _agent_keyboard(state.company_id)
        _send(token, chat_id, "Ajan değiştir — seç:", reply_markup=keyboard)
        return

    if text == "/durum":
        agent_info = (
            f"🤖 Seçili ajan: <b>{state.selected_agent_name}</b>"
            if state.selected_agent_name
            else "⚠️ Henüz ajan seçilmedi."
        )
        _send(
            token,
            chat_id,
            f"{agent_info}\n\n"
            f"🏢 Şirket: {state.company_id or '?'}\n"
            f"📋 Oturum: {state.active_session_id or 'Yeni oluşturulacak'}",
        )
        return

    if text == "/onaylar":
        approval_text, keyboard = _pending_approvals_text_and_keyboard(state.company_id)
        _send(token, chat_id, approval_text, reply_markup=keyboard)
        return

    # Route to selected agent
    if not state.selected_agent_id:
        keyboard = _agent_keyboard(state.company_id)
        _send(token, chat_id, "⚠️ Önce bir ajan seçmelisin:", reply_markup=keyboard)
        return

    # Send "thinking" message
    _send(token, chat_id, f"⏳ <b>{state.selected_agent_name}</b> düşünüyor...")

    try:
        session_id = _ensure_session(state)
        # Persist session_id in state
        if state.active_session_id != session_id:
            state.active_session_id = session_id
            _save_state(state)

        response = await _run_agent(session_id, text)

        # Format response
        header = f"🤖 <b>{state.selected_agent_name}:</b>\n\n"
        _split_and_send(token, chat_id, header + response)

    except Exception as e:
        _send(token, chat_id, f"❌ Hata: {e}")


# ── Long polling loop (runs in background thread) ─────────────────────────────

import threading
import time

_polling_thread: threading.Thread | None = None
_polling_active = False


def _polling_loop() -> None:
    """Continuously long-polls Telegram for updates. Runs in a daemon thread."""
    offset = 0
    while _polling_active:
        token = _get_bot_token()
        if not token:
            time.sleep(10)
            continue
        try:
            with httpx.Client(timeout=40) as c:
                r = c.get(
                    _tg_url(token, "getUpdates"),
                    params={
                        "timeout": 30,
                        "offset": offset,
                        "allowed_updates": ["message", "callback_query"],
                    },
                )
            if r.status_code != 200:
                time.sleep(5)
                continue
            updates = r.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    asyncio.run(_process_async(update))
                except Exception:
                    pass
        except Exception:
            time.sleep(5)


_BOT_COMMANDS = [
    {"command": "ajanlar",   "description": "Ajan seçim menüsünü aç"},
    {"command": "degistir",  "description": "Aktif ajanı değiştir"},
    {"command": "durum",     "description": "Seçili ajan ve oturum bilgisi"},
    {"command": "onaylar",   "description": "Bekleyen görev ve A2A onayları"},
]


def _register_commands(token: str) -> None:
    try:
        with httpx.Client(timeout=10) as c:
            c.post(
                _tg_url(token, "setMyCommands"),
                json={"commands": _BOT_COMMANDS},
            )
    except Exception:
        pass


def start_polling() -> None:
    global _polling_thread, _polling_active
    _polling_active = True
    token = _get_bot_token()
    if token:
        _register_commands(token)
    _polling_thread = threading.Thread(
        target=_polling_loop, daemon=True, name="tg-polling"
    )
    _polling_thread.start()


def stop_polling() -> None:
    global _polling_active
    _polling_active = False


# ── Status endpoint ────────────────────────────────────────────────────────────


@router.get("/telegram/bot-status")
async def bot_status():
    """Check bot polling status and bot info."""
    token = _get_bot_token()
    if not token:
        return {"ok": False, "error": "No bot token configured"}
    with httpx.Client(timeout=10) as c:
        r = c.get(_tg_url(token, "getMe"))
    bot_info = r.json().get("result", {})
    return {
        "ok": True,
        "polling_active": _polling_active,
        "thread_alive": _polling_thread.is_alive() if _polling_thread else False,
        "bot": bot_info,
    }
