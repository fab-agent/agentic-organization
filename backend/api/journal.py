"""Work journal — agent-authored and human-authored log entries per personnel."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import AgentSession, Personnel, User, WorkJournalEntry
from services import authz

logger = logging.getLogger("app")
router = APIRouter(prefix="/journal", tags=["journal"])


class JournalEntryCreate(BaseModel):
    personnel_id: str
    title: str | None = None
    content: str
    author: str = "human"  # "agent" | "human"
    session_id: str | None = None


class JournalEntryResponse(BaseModel):
    id: str
    personnel_id: str
    session_id: str | None
    author: str
    title: str | None
    content: str
    created_at: str


def _managed(session, user: User, personnel_id: str) -> Personnel:
    """The journal belongs to the agent: its managers (and nobody outside the
    company) may read and write it."""
    person = session.get(Personnel, personnel_id)
    if (
        not person
        or not authz.is_member(session, user.id, person.company_id)
        or not authz.can_manage_agent(session, user.id, person)
    ):
        raise HTTPException(status_code=404, detail="Personnel not found")
    return person


def _to_resp(e: WorkJournalEntry) -> JournalEntryResponse:
    return JournalEntryResponse(
        id=e.id,
        personnel_id=e.personnel_id,
        session_id=e.session_id,
        author=e.author,
        title=e.title,
        content=e.content,
        created_at=e.created_at.isoformat(),
    )


@router.get("/{personnel_id}")
def list_journal(
    personnel_id: str,
    limit: int = 50,
    user: User = Depends(get_current_user),
) -> list[JournalEntryResponse]:
    with get_session() as session:
        _managed(session, user, personnel_id)
        entries = session.exec(
            select(WorkJournalEntry)
            .where(WorkJournalEntry.personnel_id == personnel_id)
            .order_by(WorkJournalEntry.created_at.desc())
            .limit(max(1, min(limit, 200)))
        ).all()
        return [_to_resp(e) for e in entries]


@router.post("/", status_code=201)
def create_entry(
    body: JournalEntryCreate,
    user: User = Depends(get_current_user),
) -> JournalEntryResponse:
    if body.author not in ("agent", "human"):
        raise HTTPException(status_code=422, detail="author: agent | human")
    with get_session() as session:
        _managed(session, user, body.personnel_id)
        if body.session_id:
            sess = session.get(AgentSession, body.session_id)
            if not sess or sess.personnel_id != body.personnel_id:
                raise HTTPException(status_code=404, detail="Session not found")
        entry = WorkJournalEntry(
            personnel_id=body.personnel_id,
            session_id=body.session_id,
            author=body.author,
            title=body.title,
            content=body.content,
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        logger.info(
            "Journal entry created",
            extra={"extra": {"personnel_id": body.personnel_id, "author": body.author}},
        )
        return _to_resp(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        entry = session.get(WorkJournalEntry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        try:
            _managed(session, user, entry.personnel_id)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Entry not found") from None
        session.delete(entry)
        session.commit()
