"""Learning signals (ADR-0022 §3): verified human feedback on assistant answers.

What is accepted: a thumbs up/down or a short correction from an authenticated person
with a person record, about an *assistant* answer in a chat they own, in a company that
has switched work review on (ADR-0021 opt-in). Notes are redacted and short. A person
gives at most `MAX_PER_DAY` signals a day and one per (answer, kind), so one voice
cannot flood a future proposer; withdrawing is a delete. Nothing here changes any
prompt: a proposer needs several independent people before it may draft anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select

from models import AgentSession, LearningSignal, Personnel, SessionMessage, User
from services import work_review as wr
from services.redact import redact

KINDS = ("thumbs_up", "thumbs_down", "correction")
MAX_NOTE = 500
MAX_PER_DAY = 50


def record(
    session, user: User, message_id: str, kind: str, note: str | None
) -> LearningSignal:
    if kind not in KINDS:
        raise HTTPException(
            status_code=422, detail="kind: thumbs_up | thumbs_down | correction"
        )
    msg = session.get(SessionMessage, message_id)
    sess = session.get(AgentSession, msg.session_id) if msg else None
    # Only the owner of the chat, about an assistant answer.
    if not msg or not sess or msg.role != "assistant" or sess.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    agent = session.get(Personnel, sess.personnel_id)
    if not agent or not agent.company_id:
        raise HTTPException(status_code=404, detail="Not found")
    human = session.exec(
        select(Personnel).where(
            Personnel.user_id == user.id,
            Personnel.company_id == agent.company_id,
            Personnel.type == "human",
        )
    ).first()
    if not human:
        raise HTTPException(
            status_code=409, detail="No person record is linked to this account"
        )
    if not wr.enabled(session, agent.company_id):
        # With review off the loop produces and uses nothing (ADR-0022 §3).
        raise HTTPException(
            status_code=409, detail="Feedback learning is off for this company"
        )
    if kind == "correction" and not (note or "").strip():
        raise HTTPException(status_code=422, detail="A correction needs a note")
    clean = redact((note or "").strip()[:MAX_NOTE]).text or None

    existing = session.exec(
        select(LearningSignal).where(
            LearningSignal.user_id == user.id,
            LearningSignal.message_id == message_id,
            LearningSignal.kind == kind,
        )
    ).first()
    if existing:
        existing.note = clean if kind == "correction" else None
        session.add(existing)
        return existing
    since = datetime.utcnow() - timedelta(days=1)
    today = session.exec(
        select(func.count())
        .select_from(LearningSignal)
        .where(LearningSignal.user_id == user.id, LearningSignal.created_at >= since)
    ).one()
    if today >= MAX_PER_DAY:
        raise HTTPException(status_code=429, detail="Daily feedback limit reached")
    sig = LearningSignal(
        company_id=agent.company_id,
        personnel_id=human.id,
        persona_id=agent.id,
        user_id=user.id,
        session_id=sess.id,
        message_id=message_id,
        kind=kind,
        note=clean if kind == "correction" else None,
    )
    try:
        with session.begin_nested():
            session.add(sig)
            session.flush()
    except IntegrityError:
        # a concurrent identical signal won; the result is the same row
        won = session.exec(
            select(LearningSignal).where(
                LearningSignal.user_id == user.id,
                LearningSignal.message_id == message_id,
                LearningSignal.kind == kind,
            )
        ).first()
        if won is None:
            raise HTTPException(status_code=409, detail="Conflict, try again")
        return won
    return sig
