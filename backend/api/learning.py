"""Feedback on assistant answers (ADR-0022 §3). Own signals only: give, list, withdraw."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import LearningSignal, User
from services import learning

router = APIRouter(prefix="/learning", tags=["learning"])


class SignalBody(BaseModel):
    message_id: str
    kind: str
    note: str | None = Field(default=None, max_length=2000)


def _dict(s: LearningSignal) -> dict:
    return {
        "id": s.id,
        "message_id": s.message_id,
        "kind": s.kind,
        "note": s.note,
        "created_at": s.created_at.isoformat(),
    }


@router.post("/signals", status_code=201)
def give_signal(body: SignalBody, user: User = Depends(get_current_user)):
    with get_session() as session:
        sig = learning.record(session, user, body.message_id, body.kind, body.note)
        session.commit()
        session.refresh(sig)
        return _dict(sig)


@router.get("/signals/me")
def my_signals(user: User = Depends(get_current_user)):
    with get_session() as session:
        rows = session.exec(
            select(LearningSignal)
            .where(LearningSignal.user_id == user.id)
            .order_by(LearningSignal.created_at.desc())
            .limit(200)
        ).all()
        return [_dict(r) for r in rows]


@router.delete("/signals/{message_id}/{kind}", status_code=204)
def withdraw_signal(message_id: str, kind: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        sig = session.exec(
            select(LearningSignal).where(
                LearningSignal.user_id == user.id,
                LearningSignal.message_id == message_id,
                LearningSignal.kind == kind,
            )
        ).first()
        if not sig:
            raise HTTPException(status_code=404, detail="Not found")
        session.delete(sig)
        session.commit()
