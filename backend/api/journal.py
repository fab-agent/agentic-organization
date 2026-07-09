"""Work journal — agent-authored and human-authored log entries per personnel."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import Personnel, User, WorkJournalEntry

logger = logging.getLogger("app")
router = APIRouter(prefix="/journal", tags=["journal"])


class JournalEntryCreate(BaseModel):
    personnel_id: str
    title: Optional[str] = None
    content: str
    author: str = "human"          # "agent" | "human"
    session_id: Optional[str] = None


class JournalEntryResponse(BaseModel):
    id: str
    personnel_id: str
    session_id: Optional[str]
    author: str
    title: Optional[str]
    content: str
    created_at: str


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
    _: User = Depends(get_current_user),
) -> list[JournalEntryResponse]:
    with get_session() as session:
        if not session.get(Personnel, personnel_id):
            raise HTTPException(status_code=404, detail="Personnel not found")
        entries = session.exec(
            select(WorkJournalEntry)
            .where(WorkJournalEntry.personnel_id == personnel_id)
            .order_by(WorkJournalEntry.created_at.desc())
            .limit(limit)
        ).all()
        return [_to_resp(e) for e in entries]


@router.post("/", status_code=201)
def create_entry(
    body: JournalEntryCreate,
    user: User = Depends(get_current_user),
) -> JournalEntryResponse:
    with get_session() as session:
        if not session.get(Personnel, body.personnel_id):
            raise HTTPException(status_code=404, detail="Personnel not found")
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
        logger.info("Journal entry created", extra={"extra": {
            "personnel_id": body.personnel_id, "author": body.author
        }})
        return _to_resp(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: str, _: User = Depends(get_current_user)):
    with get_session() as session:
        entry = session.get(WorkJournalEntry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        session.delete(entry)
        session.commit()
