"""One company's operational picture (ADR-0034): existing views combined, nothing new measured.

Every section is computed on its own and reports a status (`ok` / `warn` / `fail` / `unknown`).
A section that cannot be computed answers `unknown` with a short stable reason code - never an
exception text, a path or key material - and does not take the others down. All queries are
bounded by the company id given by the caller, whose right to see it is decided by the endpoint.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import select

from api.system import APP_VERSION
from database import get_session
from models import (
    AuditEvent,
    GatewayUsage,
    Personnel,
    RunDiagnosis,
    WorkspaceManifestState,
)

logger = logging.getLogger("app")

ORDER = {"ok": 0, "unknown": 1, "warn": 2, "fail": 3}
CERT_WARN_SECONDS = 14 * 24 * 3600
EVAL_DAYS = 30
TOP_AGENTS = 5


def worst(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: ORDER[s]) if statuses else "unknown"


def _guard(name: str, fn):
    try:
        return fn()
    except Exception:  # one broken section must not hide the others
        logger.exception("monitoring section %s failed", name)
        return {"status": "unknown", "reason": "section_failed"}


def _service() -> dict:
    with get_session() as session:
        session.exec(select(1)).one()
    return {"status": "ok", "version": APP_VERSION, "database": "ok"}


def _audit(company_id: str, deep: bool) -> dict:
    from services import audit_anchor, audit_chain

    with get_session() as session:
        head = session.exec(
            select(func.max(AuditEvent.seq)).where(AuditEvent.chain_key == company_id)
        ).one()
    out: dict = {"events": head or 0}
    # Anchors compare the live head with the append-only external record: cheap, and the one
    # check that catches a rebuilt shorter chain. The full re-hash reads every event: on request.
    anchors = audit_anchor.check_anchors(only={company_id}, verify_internal=False)
    mine = anchors["chains"].get(company_id)
    out["anchor"] = mine["state"] if mine else "none_recorded"
    out["anchor_issues"] = len(anchors["issues"])
    status = "ok"
    if anchors["issues"]:
        status = "fail"
    elif not mine and out["events"]:
        status = "warn"  # a chain nobody has anchored yet is not protected against truncation
    if deep:
        v = audit_chain.verify(company_id)
        out["verified"] = bool(v["ok"])
        if not v["ok"]:
            out["broken_at"] = v.get("broken_at")
            status = "fail"
    else:
        out["verified"] = None  # not checked in this request
    out["status"] = status
    return out


def _gateway(company_id: str, now: datetime) -> dict:
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    agents = select(Personnel.id).where(Personnel.company_id == company_id)
    with get_session() as session:
        rows = session.exec(
            select(GatewayUsage).where(
                GatewayUsage.persona_id.in_(agents),
                GatewayUsage.period.in_([day, month]),
            )
        ).all()
        names = {
            p.id: p.name
            for p in session.exec(
                select(Personnel).where(Personnel.company_id == company_id)
            ).all()
        }
    totals = {
        "day": {"requests": 0, "tokens_in": 0, "tokens_out": 0},
        "month": {"requests": 0, "tokens_in": 0, "tokens_out": 0},
    }
    today = []
    for r in rows:
        key = "day" if r.period == day else "month"
        t = totals[key]
        t["requests"] += r.requests
        t["tokens_in"] += r.tokens_in
        t["tokens_out"] += r.tokens_out
        if key == "day":
            today.append(
                {
                    "persona_id": r.persona_id,
                    "name": names.get(r.persona_id),
                    "requests": r.requests,
                    "tokens": r.tokens_in + r.tokens_out,
                }
            )
    today.sort(key=lambda a: a["tokens"], reverse=True)
    return {"status": "ok", **totals, "top_agents_today": today[:TOP_AGENTS]}


def _eval(company_id: str, now: datetime) -> dict:
    since = now - timedelta(days=EVAL_DAYS)
    with get_session() as session:
        rows = session.exec(
            select(RunDiagnosis).where(
                RunDiagnosis.company_id == company_id, RunDiagnosis.created_at >= since
            )
        ).all()
    layers: dict[str, int] = {}
    for r in rows:
        if r.suspect_layer:
            layers[r.suspect_layer] = layers.get(r.suspect_layer, 0) + 1
    return {
        "status": "ok",
        "days": EVAL_DAYS,
        "runs": len(rows),
        "suspect_counts": layers,  # stage-1 hypotheses, not fault rates (ADR-0023)
        "truncated": sum(1 for r in rows if r.truncated),
        "invalid_events": sum(r.invalid_events for r in rows),
    }


def _workspace(company_id: str, now_s: int) -> dict:
    from services import workspace_service as ws

    out: dict = {}
    status = "ok"
    try:
        signer = ws.load_signer(now_s)
        not_after = int(signer.cert.get("not_after", 0))
        out.update(signer="ok", epoch=signer.epoch, crl_number=signer.crl_number)
        out["signing_cert_days_left"] = max(0, (not_after - now_s) // 86400)
        if not_after - now_s < CERT_WARN_SECONDS:
            status = "warn"
    except ws.WorkspaceUnavailable as e:
        # the stable code only; the reason text could name a file
        out.update(signer="unavailable", reason=str(e)[:48])
        status = "fail"
    with get_session() as session:
        states = session.exec(
            select(WorkspaceManifestState).where(
                WorkspaceManifestState.company_id == company_id
            )
        ).all()
    out["people_issued"] = len(states)
    out["last_issued"] = (
        max(s.updated_at for s in states).isoformat() + "Z" if states else None
    )
    out["status"] = status
    return out


def summary(company_id: str, *, deep: bool = False) -> dict:
    now = datetime.utcnow()
    sections = {
        "service": _guard("service", _service),
        "audit": _guard("audit", lambda: _audit(company_id, deep)),
        "gateway": _guard("gateway", lambda: _gateway(company_id, now)),
        "eval": _guard("eval", lambda: _eval(company_id, now)),
        "workspace": _guard(
            "workspace", lambda: _workspace(company_id, int(time.time()))
        ),
        # Clients do not report their state yet (ADR-0026 decision 4): say so, do not guess.
        "clients": {"status": "unknown", "reason": "drift_not_reported"},
    }
    return {
        "company_id": company_id,
        "generated_at": now.isoformat() + "Z",
        "status": worst([s["status"] for s in sections.values()]),
        "sections": sections,
    }
