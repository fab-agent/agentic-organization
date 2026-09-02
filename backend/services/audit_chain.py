"""
Tamper-evident audit chain (ADR-0006).

Each `AuditEvent` carries `prev_hash` and a `hash` over its canonical body:

    hash = sha256( prev_hash \\n chain_key \\n seq \\n canonical_json(body) )

so deleting or altering any row breaks verification from that row onward, and a
row cannot be moved to another chain.

**One chain per tenant.** `chain_key` is the company id, or "__global__" for
events with no company. `seq` is monotonic within a chain.

- `append(...)`    — add one event to its tenant chain.
- `record(...)`    — `append()` + mirror a legacy `AuditLog` row so the existing
                     `/audit` UI keeps showing everything.
- `verify(company_id=None)` / `verify_all()` — walk a chain / every chain.
- `ingest_batch()` — the laptop plugin's one-way feed (`POST /audit/ingest`).

Concurrency: on PostgreSQL each `append()` takes a transaction-scoped advisory
lock keyed by the chain, so multiple uvicorn workers / the scheduler process
cannot race the read-last-then-insert. On SQLite the DB serialises writers and an
in-process lock covers the common single-process case (ADR-0006 notes this).
"""

from __future__ import annotations

import hashlib
import json
import threading
import zlib
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlmodel import select

from database import get_session
from models import AuditEvent, AuditLog

GENESIS_HASH = "0" * 64
GLOBAL_CHAIN = "__global__"

_lock = threading.Lock()


def _chain_key(company_id: str | None) -> str:
    return company_id or GLOBAL_CHAIN


def _canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_hash(prev_hash: str, chain_key: str, seq: int, body: dict) -> str:
    return hashlib.sha256(
        f"{prev_hash}\n{chain_key}\n{seq}\n{_canonical(body)}".encode()
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


def _advisory_lock(session, chain_key: str) -> None:
    """PostgreSQL: transaction-scoped advisory lock keyed by the chain."""
    if session.bind.dialect.name == "postgresql":
        key = zlib.crc32(chain_key.encode()) & 0x7FFFFFFF
        session.exec(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=key))


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
    """Add one event to its tenant chain. Returns the persisted `AuditEvent`."""
    created = created_at or datetime.utcnow()
    chain_key = _chain_key(company_id)
    with _lock:
        with get_session() as session:
            _advisory_lock(session, chain_key)
            last = session.exec(
                select(AuditEvent)
                .where(AuditEvent.chain_key == chain_key)
                .order_by(AuditEvent.seq.desc())
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
                chain_key=chain_key,
                seq=seq,
                prev_hash=prev_hash,
                hash=_compute_hash(prev_hash, chain_key, seq, body),
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
    `append()` to the tenant chain and mirror a legacy `AuditLog` row. Best-effort:
    an audit failure must never crash the caller (callers that need fail-closed
    behaviour check chain reachability themselves — ADR-0006).
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
                        {
                            "chain": ev.chain_key,
                            "seq": ev.seq,
                            "reason": reason,
                            **(payload or {}),
                        },
                        ensure_ascii=False,
                    ),
                    created_at=ev.created_at,
                )
            )
            session.commit()
    except Exception:
        pass
    return ev


def _verify_chain(events: list[AuditEvent]) -> dict:
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
        if _compute_hash(ev.prev_hash, ev.chain_key, ev.seq, _body_of(ev)) != ev.hash:
            return {
                "ok": False,
                "broken_at": ev.seq,
                "detail": "hash mismatch — record was altered",
            }
        prev_hash = ev.hash
    return {"ok": True, "count": len(events), "head": prev_hash}


def verify(company_id: str | None = None) -> dict:
    """Verify one tenant chain (or the global chain when company_id is None)."""
    chain_key = _chain_key(company_id)
    with get_session() as session:
        events = list(
            session.exec(
                select(AuditEvent)
                .where(AuditEvent.chain_key == chain_key)
                .order_by(AuditEvent.seq)
            ).all()
        )
    return {"chain_key": chain_key, **_verify_chain(events)}


def verify_all() -> dict:
    """Verify every chain. `{"ok": <all ok>, "chains": {chain_key: result}}`."""
    with get_session() as session:
        keys = list(session.exec(select(AuditEvent.chain_key).distinct()).all())
    chains = {k: verify(None if k == GLOBAL_CHAIN else k) for k in sorted(keys)}
    return {"ok": all(c["ok"] for c in chains.values()), "chains": chains}


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
