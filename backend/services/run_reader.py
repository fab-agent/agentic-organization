"""Select and diagnose the audit events of one run (ADR-0023).

The caller has already authorised access to (company, persona). Events are matched
on the company chain, the persona as actor and the `payload.run.run_id` that the
server stamped from the verified token. A client-supplied session reference is never
used to join events to a run: an event without that stamp is simply not part of it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from models import AuditEvent, RunDiagnosis
from services.run_diagnosis import MAX_EVENTS, Diagnosis, Finding, diagnose

DIAGNOSER_VERSION = 1
# Run ids are minted by the server (uuid-like); anything else is not a run.
RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Re-diagnosing the same run inside this window returns the stored result.
FRESH_FOR = timedelta(seconds=10)


def events_for_run(
    session, company_id: str, persona_id: str, run_id: str
) -> tuple[list[dict], bool]:
    """The run's events (oldest first) and whether more existed than we return.

    A SQL substring prefilter on the stored JSON keeps the scan to this run's rows;
    the exact `payload.run.run_id` match is still checked in Python.
    """
    rows = session.exec(
        select(AuditEvent)
        .where(
            AuditEvent.chain_key == company_id,
            AuditEvent.actor_id == persona_id,
            AuditEvent.payload_json.contains(run_id),
        )
        .order_by(AuditEvent.seq)
    ).all()
    out: list[dict] = []
    truncated = False
    for r in rows:
        try:
            payload = json.loads(r.payload_json) if r.payload_json else {}
        except ValueError:
            continue
        run = payload.get("run") if isinstance(payload, dict) else None
        if not (isinstance(run, dict) and run.get("run_id") == run_id):
            continue
        if len(out) >= MAX_EVENTS:
            truncated = True
            break
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
    return out, truncated


def _apply(row: RunDiagnosis, d, truncated: bool) -> None:
    row.suspect_layer = d.suspect_layer
    row.scores_json = json.dumps(d.scores)
    row.findings_json = json.dumps([f.as_dict() for f in d.findings])
    row.events_seen = d.events_seen
    row.ignored_client_claims = d.ignored_client_claims
    row.invalid_events = d.invalid_events
    row.truncated = bool(d.truncated or truncated)
    row.diagnoser_version = DIAGNOSER_VERSION
    row.updated_at = datetime.utcnow()


def diagnose_and_store(
    session, company_id: str, persona_id: str, run_id: str
) -> RunDiagnosis | None:
    """Recompute from the chain and store. None when the run has no events at all.

    Nothing is written for an unknown run, a fresh stored result is returned as is,
    and an empty recomputation never replaces an earlier non-empty one.
    """
    key = (company_id, persona_id, run_id)
    row = session.get(RunDiagnosis, key)
    if row and datetime.utcnow() - row.updated_at < FRESH_FOR:
        return row
    events, truncated = events_for_run(session, company_id, persona_id, run_id)
    if not events:
        return row  # earlier result (if any) is kept; unknown run stays unknown
    d = diagnose(events, run_id=run_id)
    for attempt in (1, 2):
        row = session.get(RunDiagnosis, key)
        if row is None:
            row = RunDiagnosis(
                company_id=company_id, persona_id=persona_id, run_id=run_id
            )
        _apply(row, d, truncated)
        session.add(row)
        try:
            session.commit()
            break
        except IntegrityError:  # a concurrent request created it first: update that
            session.rollback()
            if attempt == 2:
                raise
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


def diagnosis_from_row(row: RunDiagnosis) -> Diagnosis:
    """Rebuild the stage-1 result from a stored row (findings are plain data)."""
    findings = []
    for f in json.loads(row.findings_json):
        ev = f.get("evidence")
        findings.append(
            Finding(
                f.get("layer", ""),
                f.get("kind", ""),
                f.get("severity", "info"),
                f.get("detail", ""),
                tuple(ev) if isinstance(ev, list) and len(ev) == 2 else None,
            )
        )
    return Diagnosis(
        run_id=row.run_id,
        findings=findings,
        scores=json.loads(row.scores_json),
        suspect_layer=row.suspect_layer,
        events_seen=row.events_seen,
        ignored_client_claims=row.ignored_client_claims,
        invalid_events=row.invalid_events,
        truncated=row.truncated,
    )
