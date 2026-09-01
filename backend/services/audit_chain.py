"""
Tamper-evident audit chain (ADR-0006).

Each `AuditEvent` carries `prev_hash` and a `hash` over its canonical body:

    hash = sha256( prev_hash \\n seq \\n canonical_json(body) )

so deleting or altering any row breaks verification from that row onward.

- `append(...)`    — add one event to the chain.
- `record(...)`    — `append()` + mirror a legacy `AuditLog` row so the existing
                     `/audit` UI keeps showing everything.
- `verify()`       — walk the whole chain and report the first break, if any.
- `ingest_batch()` — the laptop plugin's one-way feed (`POST /audit/ingest`).

Known limits (ADR-0006 open questions): single global chain (not per-tenant);
SQLite serializes writers but a cross-process lock is not held here; the chain
head is not yet anchored anywhere external.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from typing import Any

from sqlmodel import select

from database import get_session
from models import AuditEvent, AuditLog

GENESIS_HASH = "0" * 64

# Serialises the read-last-then-insert critical section within this process.
_lock = threading.Lock()


def _canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_hash(prev_hash: str, seq: int, body: dict) -> str:
    return hashlib.sha256(
        f"{prev_hash}\n{seq}\n{_canonical(body)}".encode()
    ).hexdigest()


def _body(
    *,
    actor_type: str,
    actor_id: str | None,
    company_id: str | None,
    action: str,
    target: str | None,
    reason: str | None,
    payload: dict | None,
    created_at_iso: str,
) -> dict:
    return {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "company_id": company_id,
        "action": action,
        "target": target,
        "reason": reason,
        "payload": payload or {},
        "created_at": created_at_iso,
    }


def _body_of(ev: AuditEvent) -> dict:
    return _body(
        actor_type=ev.actor_type,
        actor_id=ev.actor_id,
        company_id=ev.company_id,
        action=ev.action,
        target=ev.target,
        reason=ev.reason,
        payload=json.loads(ev.payload_json) if ev.payload_json else {},
        created_at_iso=ev.created_at.isoformat(),
    )


def append(
    *,
    actor_type: str,
    action: str,
    actor_id: str | None = None,
    company_id: str | None = None,
    target: str | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> AuditEvent:
    """Add one event to the chain. Returns the persisted `AuditEvent`."""
    created = created_at or datetime.utcnow()
    with _lock:
        with get_session() as session:
            last = session.exec(
                select(AuditEvent).order_by(AuditEvent.seq.desc())
            ).first()
            seq = (last.seq + 1) if last else 1
            prev_hash = last.hash if last else GENESIS_HASH
            body = _body(
                actor_type=actor_type,
                actor_id=actor_id,
                company_id=company_id,
                action=action,
                target=target,
                reason=reason,
                payload=payload,
                created_at_iso=created.isoformat(),
            )
            ev = AuditEvent(
                seq=seq,
                prev_hash=prev_hash,
                hash=_compute_hash(prev_hash, seq, body),
                actor_type=actor_type,
                actor_id=actor_id,
                company_id=company_id,
                action=action,
                target=target,
                reason=reason,
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
                created_at=created,
            )
            session.add(ev)
            session.commit()
            session.refresh(ev)
            return ev


def record(
    *,
    actor_type: str,
    action: str,
    actor_id: str | None = None,
    company_id: str | None = None,
    target: str | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent | None:
    """
    `append()` to the chain and mirror a legacy `AuditLog` row. Best-effort: an
    audit failure must never crash the caller (callers that need fail-closed
    behaviour check the chain reachability themselves — ADR-0006).
    """
    try:
        ev = append(
            actor_type=actor_type,
            action=action,
            actor_id=actor_id,
            company_id=company_id,
            target=target,
            reason=reason,
            payload=payload,
        )
    except Exception:
        return None

    try:
        with get_session() as session:
            session.add(
                AuditLog(
                    company_id=company_id,
                    action=action,
                    entity_type=actor_type,
                    entity_id=actor_id,
                    entity_name=target,
                    details_json=json.dumps(
                        {"seq": ev.seq, "reason": reason, **(payload or {})},
                        ensure_ascii=False,
                    ),
                    created_at=ev.created_at,
                )
            )
            session.commit()
    except Exception:
        pass
    return ev


def verify() -> dict:
    """
    Walk the chain in `seq` order. Returns
    `{"ok": True, "count": n, "head": <hash>}` or
    `{"ok": False, "broken_at": <seq>, "detail": <str>}`.
    """
    with get_session() as session:
        events = list(session.exec(select(AuditEvent).order_by(AuditEvent.seq)).all())

    prev_hash = GENESIS_HASH
    for i, ev in enumerate(events, start=1):
        if ev.seq != i:
            return {
                "ok": False,
                "broken_at": ev.seq,
                "detail": f"seq gap (expected {i})",
            }
        if ev.prev_hash != prev_hash:
            return {"ok": False, "broken_at": ev.seq, "detail": "prev_hash mismatch"}
        if _compute_hash(ev.prev_hash, ev.seq, _body_of(ev)) != ev.hash:
            return {
                "ok": False,
                "broken_at": ev.seq,
                "detail": "hash mismatch — record was altered",
            }
        prev_hash = ev.hash

    return {"ok": True, "count": len(events), "head": prev_hash}


def ingest_batch(
    events: list[dict], *, actor_id: str | None, company_id: str | None
) -> int:
    """
    Append a batch from the workstation plugin. Each item:
    `{action, target?, reason?, payload?}`. Returns the number appended.
    """
    n = 0
    for item in events:
        action = (item or {}).get("action")
        if not action:
            continue
        append(
            actor_type="agent",
            actor_id=actor_id,
            company_id=company_id,
            action=str(action),
            target=item.get("target"),
            reason=item.get("reason"),
            payload=item.get("payload")
            if isinstance(item.get("payload"), dict)
            else None,
        )
        n += 1
    return n
