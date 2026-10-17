"""Select and diagnose the audit events of one run (ADR-0023).

The caller has already authorised access to (company, persona). Events are matched
on the company chain, the persona as actor and the `payload.run.run_id` that the
server stamped from the verified token. A client-supplied session reference is never
used to join events to a run: an event without that stamp is simply not part of it.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import select

from models import AuditEvent, RunDiagnosis
from services.run_diagnosis import MAX_EVENTS, diagnose

DIAGNOSER_VERSION = 1
# Bounded scan: a persona's recent rows on its company chain, newest first.
_SCAN_LIMIT = 20000


def events_for_run(
    session, company_id: str, persona_id: str, run_id: str
) -> list[dict]:
    rows = session.exec(
        select(AuditEvent)
        .where(AuditEvent.chain_key == company_id, AuditEvent.actor_id == persona_id)
        .order_by(AuditEvent.seq.desc())
        .limit(_SCAN_LIMIT)
    ).all()
    out: list[dict] = []
    for r in reversed(rows):
        try:
            payload = json.loads(r.payload_json) if r.payload_json else {}
        except ValueError:
            continue
        run = payload.get("run") if isinstance(payload, dict) else None
        if isinstance(run, dict) and run.get("run_id") == run_id:
            out.append(
                {
                    "action": r.action,
                    "target": r.target,
                    "reason": r.reason,
                    "payload": payload,
                    "chain_key": r.chain_key,
                    "seq": r.seq,
                }
            )
            if len(out) >= MAX_EVENTS:
                break
    return out


def diagnose_and_store(
    session, company_id: str, persona_id: str, run_id: str
) -> RunDiagnosis:
    """Recompute from the chain and upsert; safe to call repeatedly."""
    d = diagnose(events_for_run(session, company_id, persona_id, run_id), run_id=run_id)
    row = session.get(RunDiagnosis, (company_id, persona_id, run_id))
    now = datetime.utcnow()
    if row is None:
        row = RunDiagnosis(company_id=company_id, persona_id=persona_id, run_id=run_id)
    row.suspect_layer = d.suspect_layer
    row.scores_json = json.dumps(d.scores)
    row.findings_json = json.dumps([f.as_dict() for f in d.findings])
    row.events_seen = d.events_seen
    row.ignored_client_claims = d.ignored_client_claims
    row.invalid_events = d.invalid_events
    row.truncated = d.truncated
    row.diagnoser_version = DIAGNOSER_VERSION
    row.updated_at = now
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def to_dict(row: RunDiagnosis) -> dict:
    return {
        "run_id": row.run_id,
        "persona_id": row.persona_id,
        "suspect_layer": row.suspect_layer,
        "scores": json.loads(row.scores_json),
        "findings": json.loads(row.findings_json),
        "events_seen": row.events_seen,
        "ignored_client_claims": row.ignored_client_claims,
        "invalid_events": row.invalid_events,
        "truncated": row.truncated,
        "diagnoser_version": row.diagnoser_version,
        "updated_at": row.updated_at.isoformat(),
        "note": "Signals from the audit trail, not proof; confirm by replay.",
    }
