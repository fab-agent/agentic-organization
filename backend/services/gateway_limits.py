"""
LLM gateway guardrails (ADR-0004): model allow-list, per-persona token quota,
per-persona rate limit.

Config lives in `AppConfig`, resolved company-first then global:
  gateway.model_allow[:<company_id>]   comma globs; default "*" (allow all)
  gateway.daily_token_limit            int; 0 = unlimited (default)
  gateway.monthly_token_limit          int; 0 = unlimited (default)
  gateway.rpm_limit                    requests/min per persona; 0 = off (default)

Defaults are permissive so the gateway does not start rejecting traffic the day
it ships — an operator tightens per company (same philosophy as the Policy
Engine's `dry_run`). Rate limiting is an in-process sliding window; multi-worker
deployments need a shared store (Redis) — noted like the audit-chain lock.
"""

from __future__ import annotations

import fnmatch
import threading
import time
from collections import deque
from datetime import datetime

from fastapi import HTTPException
from sqlmodel import select

from database import get_session
from models import AppConfig, GatewayUsage

_rl_lock = threading.Lock()
_rl_hits: dict[str, deque[float]] = {}


def _cfg(key: str, company_id: str | None, default: str) -> str:
    with get_session() as session:
        if company_id:
            row = session.get(AppConfig, f"{key}:{company_id}")
            if row and row.value:
                return row.value
        row = session.get(AppConfig, key)
        return row.value if row and row.value else default


def _int_cfg(key: str, company_id: str | None, default: int = 0) -> int:
    try:
        return int(_cfg(key, company_id, str(default)))
    except (TypeError, ValueError):
        return default


# ── Model allow-list ────────────────────────────────────────────────────────


def check_model_allowed(
    model: str, company_id: str | None, agent_model: str | None
) -> None:
    raw = _cfg("gateway.model_allow", company_id, "*")
    globs = [g.strip() for g in raw.split(",") if g.strip()] or ["*"]
    if agent_model:  # the persona's own configured model is always allowed
        globs.append(agent_model)
    if not any(fnmatch.fnmatch(model, g) for g in globs):
        raise HTTPException(
            status_code=403,
            detail=f"Model '{model}' is not on this organisation's allow-list",
        )


# ── Rate limit ──────────────────────────────────────────────────────────────


def check_rate_limit(persona_id: str, company_id: str | None) -> None:
    rpm = _int_cfg("gateway.rpm_limit", company_id, 0)
    if rpm <= 0:
        return
    now = time.monotonic()
    with _rl_lock:
        dq = _rl_hits.setdefault(persona_id, deque())
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= rpm:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit: {rpm} requests/min for this persona",
            )
        dq.append(now)


# ── Token quota ─────────────────────────────────────────────────────────────


def _periods() -> tuple[str, str]:
    d = datetime.utcnow()
    return d.strftime("%Y-%m-%d"), d.strftime("%Y-%m")


def check_token_quota(persona_id: str, company_id: str | None) -> None:
    daily = _int_cfg("gateway.daily_token_limit", company_id, 0)
    monthly = _int_cfg("gateway.monthly_token_limit", company_id, 0)
    if daily <= 0 and monthly <= 0:
        return
    day, month = _periods()
    with get_session() as session:
        rows = session.exec(
            select(GatewayUsage).where(
                GatewayUsage.persona_id == persona_id,
                GatewayUsage.period.in_([day, month]),
            )
        ).all()
    used = {r.period: r.tokens_in + r.tokens_out for r in rows}
    if daily > 0 and used.get(day, 0) >= daily:
        raise HTTPException(status_code=429, detail="Daily token quota exceeded")
    if monthly > 0 and used.get(month, 0) >= monthly:
        raise HTTPException(status_code=429, detail="Monthly token quota exceeded")


def preflight(
    persona_id: str, company_id: str | None, model: str, agent_model: str | None
) -> None:
    """All checks that must pass before the request is forwarded upstream."""
    check_model_allowed(model, company_id, agent_model)
    check_rate_limit(persona_id, company_id)
    check_token_quota(persona_id, company_id)


def record_usage(
    persona_id: str,
    company_id: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
) -> None:
    """Increment the day and month counters. Best-effort."""
    try:
        ti, to = int(tokens_in or 0), int(tokens_out or 0)
        now = datetime.utcnow()
        with get_session() as session:
            for period in _periods():
                row = session.get(GatewayUsage, (persona_id, period))
                if row:
                    row.requests += 1
                    row.tokens_in += ti
                    row.tokens_out += to
                    row.updated_at = now
                else:
                    row = GatewayUsage(
                        persona_id=persona_id,
                        period=period,
                        company_id=company_id,
                        requests=1,
                        tokens_in=ti,
                        tokens_out=to,
                    )
                session.add(row)
            session.commit()
    except Exception:
        pass
