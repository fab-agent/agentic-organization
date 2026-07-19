"""
Demo tenant OTP login
─────────────────────
POST /auth/demo/request-otp   → send 6-digit code to email
POST /auth/demo/verify-otp    → verify code, return JWT as demo user

Rate limit : 1 OTP per email per 5 minutes
OTP TTL    : 15 minutes
Role       : executive on the 'demo' company slug
"""

import logging
import os
import secrets
import smtplib
import string
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.auth import create_access_token
from database import get_session
from models import Company, CompanyMember, DemoOtp, User

log = logging.getLogger("app")
router = APIRouter(prefix="/auth/demo", tags=["demo"])

DEMO_SLUG = "demo"
OTP_TTL_MINUTES = 15
RATE_LIMIT_MINUTES = 5


# ── Request models ────────────────────────────────────────────────────────────


class OtpRequestBody(BaseModel):
    email: str


class OtpVerifyBody(BaseModel):
    email: str
    code: str


# ── Email sending ─────────────────────────────────────────────────────────────


def _send_otp_email(to_email: str, code: str) -> bool:
    """Send OTP via Gmail SMTP. Returns True on success, False if not configured."""
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_pass:
        log.warning(f"[demo-otp] SMTP not configured — OTP for {to_email}: {code}")
        return False

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{code} — fab.engineering Demo Erişim Kodu"
    msg["From"] = smtp_user
    msg["To"] = to_email

    html = f"""
    <div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:24px">
        <div style="width:36px;height:36px;background:#6366f1;border-radius:10px;display:flex;align-items:center;justify-content:center">
          <span style="color:#fff;font-weight:700;font-size:14px">f</span>
        </div>
        <span style="font-weight:700;font-size:18px;letter-spacing:-0.5px">fab.engineering</span>
      </div>
      <h2 style="font-size:20px;font-weight:600;margin:0 0 8px">Demo Erişim Kodunuz</h2>
      <p style="color:#71717a;font-size:14px;margin:0 0 24px">
        Aşağıdaki kodu <strong>demo.agent.fab.engineering</strong> adresine girin.
        Kod <strong>{OTP_TTL_MINUTES} dakika</strong> geçerlidir.
      </p>
      <div style="background:#f4f4f5;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px">
        <span style="font-size:40px;font-weight:700;letter-spacing:8px;color:#18181b">{code}</span>
      </div>
      <p style="color:#a1a1aa;font-size:12px;margin:0">
        Bu kodu siz istemediyseniz görmezden gelebilirsiniz.
      </p>
    </div>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_user, to_email, msg.as_string())
        return True
    except Exception as e:
        log.error(f"[demo-otp] SMTP error: {e}")
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_demo_company() -> Company | None:
    with get_session() as s:
        return s.exec(select(Company).where(Company.slug == DEMO_SLUG)).first()


def _ensure_demo_user(email: str, company_id: str) -> str:
    """Get or create a User + CompanyMember(executive) for this email in demo company."""
    with get_session() as s:
        user = s.exec(select(User).where(User.email == email)).first()
        if not user:
            name = email.split("@")[0].replace(".", " ").title()
            user = User(email=email, name=name, is_active=True)
            s.add(user)
            s.flush()

        member = s.exec(
            select(CompanyMember)
            .where(CompanyMember.user_id == user.id)
            .where(CompanyMember.company_id == company_id)
        ).first()
        if not member:
            member = CompanyMember(
                user_id=user.id, company_id=company_id, role="executive"
            )
            s.add(member)

        s.commit()
        return user.id


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/request-otp")
def request_otp(body: OtpRequestBody):
    email = body.email.lower().strip()

    demo = _get_demo_company()
    if not demo:
        raise HTTPException(404, "Demo tenant not found")

    now = datetime.utcnow()

    # Rate limit: 1 OTP per email per RATE_LIMIT_MINUTES
    with get_session() as s:
        recent = s.exec(
            select(DemoOtp)
            .where(DemoOtp.email == email)
            .where(DemoOtp.created_at >= now - timedelta(minutes=RATE_LIMIT_MINUTES))
        ).first()
        if recent:
            wait_sec = int(
                (
                    recent.created_at + timedelta(minutes=RATE_LIMIT_MINUTES) - now
                ).total_seconds()
            )
            raise HTTPException(429, f"Lütfen {wait_sec} saniye bekleyin.")

    # Generate and store OTP
    code = "".join(secrets.choice(string.digits) for _ in range(6))
    with get_session() as s:
        otp = DemoOtp(
            email=email,
            code=code,
            expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
        )
        s.add(otp)
        s.commit()

    email_sent = _send_otp_email(email, code)

    response: dict = {"sent": email_sent, "expires_in_minutes": OTP_TTL_MINUTES}
    if not email_sent:
        # SMTP not configured — return code in response for testing
        response["code"] = code
        response["note"] = "SMTP not configured — code returned for testing"

    return response


@router.post("/verify-otp")
def verify_otp(body: OtpVerifyBody):
    email = body.email.lower().strip()
    code = body.code.strip()
    now = datetime.utcnow()

    demo = _get_demo_company()
    if not demo:
        raise HTTPException(404, "Demo tenant not found")

    with get_session() as s:
        otp = s.exec(
            select(DemoOtp)
            .where(DemoOtp.email == email)
            .where(DemoOtp.code == code)
            .where(DemoOtp.used == False)  # noqa: E712
            .where(DemoOtp.expires_at > now)
        ).first()

        if not otp:
            raise HTTPException(401, "Kod hatalı veya süresi dolmuş.")

        otp.used = True
        s.add(otp)
        s.commit()

    user_id = _ensure_demo_user(email, demo.id)
    token = create_access_token(user_id)
    return {"access_token": token, "token_type": "bearer"}
