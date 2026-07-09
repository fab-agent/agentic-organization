"""Telegram Bot API wrapper — notification delivery channel."""
from typing import Optional

import httpx

_BASE = "https://api.telegram.org/bot{token}/{method}"


def _url(token: str, method: str) -> str:
    return _BASE.format(token=token, method=method)


def test_bot(bot_token: str) -> Optional[dict]:
    """Call getMe; return bot info dict or None on failure."""
    try:
        r = httpx.get(_url(bot_token, "getMe"), timeout=10)
        if r.status_code == 200:
            return r.json().get("result")
    except Exception:
        pass
    return None


def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    try:
        r = httpx.post(
            _url(bot_token, "sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


# ── Notification helpers ──────────────────────────────────────────────────────

def notify_invite(
    bot_token: str,
    chat_id: str,
    name: str,
    email: str,
    company_name: str,
    temp_password: str,
    app_url: str = "http://localhost:5173",
) -> None:
    text = (
        f"👤 <b>Yeni Kullanıcı Daveti</b>\n\n"
        f"Ad: <b>{name}</b>\n"
        f"E-posta: <code>{email}</code>\n"
        f"Şirket: {company_name}\n\n"
        f"🔑 Geçici şifre: <code>{temp_password}</code>\n"
        f"⏱ 30 dakika geçerlidir.\n\n"
        f"🔗 {app_url}/login"
    )
    send_message(bot_token, chat_id, text)


def notify_temp_password(
    bot_token: str,
    chat_id: str,
    name: str,
    email: str,
    temp_password: str,
    app_url: str = "http://localhost:5173",
) -> None:
    text = (
        f"🔄 <b>Geçici Şifre Yenilendi</b>\n\n"
        f"Kullanıcı: <b>{name}</b> (<code>{email}</code>)\n"
        f"Önceki şifrenin süresi dolmuştu.\n\n"
        f"🔑 Yeni geçici şifre: <code>{temp_password}</code>\n"
        f"⏱ 30 dakika geçerlidir.\n\n"
        f"🔗 {app_url}/login"
    )
    send_message(bot_token, chat_id, text)


def notify_admin_reset(
    bot_token: str,
    chat_id: str,
    name: str,
    email: str,
    temp_password: str,
    app_url: str = "http://localhost:5173",
) -> None:
    text = (
        f"🔐 <b>Yönetici Şifre Sıfırlama</b>\n\n"
        f"Kullanıcı: <b>{name}</b> (<code>{email}</code>)\n\n"
        f"🔑 Yeni geçici şifre: <code>{temp_password}</code>\n"
        f"⏱ 30 dakika geçerlidir.\n\n"
        f"🔗 {app_url}/login"
    )
    send_message(bot_token, chat_id, text)
