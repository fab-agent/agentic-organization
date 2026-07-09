import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import AgentSession, SessionMessage, Personnel, User
from schemas import SessionCreate, MessageCreate
from services.agent_runtime import run_session
from services.memory_service import generate_session_summary

router = APIRouter(tags=["sessions"])


def _session_to_dict(s: AgentSession, messages: list[SessionMessage] | None = None) -> dict:
    d = {
        "id": s.id,
        "personnel_id": s.personnel_id,
        "title": s.title,
        "status": s.status,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }
    if messages is not None:
        d["messages"] = [_message_to_dict(m) for m in messages]
    return d


def _message_to_dict(m: SessionMessage) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "tool_calls": json.loads(m.tool_calls_json) if m.tool_calls_json else [],
        "tool_results": json.loads(m.tool_results_json) if m.tool_results_json else [],
        "tokens_used": m.tokens_used,
        "created_at": m.created_at.isoformat(),
    }


# ── Session CRUD ──────────────────────────────────────────────────────────────

@router.get("/sessions")
def list_sessions(personnel_id: Optional[str] = None, status: Optional[str] = None,
                  _: User = Depends(get_current_user)):
    with get_session() as session:
        q = select(AgentSession).order_by(AgentSession.updated_at.desc())
        if personnel_id:
            q = q.where(AgentSession.personnel_id == personnel_id)
        if status:
            q = q.where(AgentSession.status == status)
        rows = session.exec(q).all()

        result = []
        for s in rows:
            last_msg = session.exec(
                select(SessionMessage)
                .where(SessionMessage.session_id == s.id)
                .order_by(SessionMessage.created_at.desc())
            ).first()
            d = _session_to_dict(s)
            d["last_message"] = _message_to_dict(last_msg) if last_msg else None
            result.append(d)
        return result


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate, _: User = Depends(get_current_user)):
    with get_session() as session:
        person = session.get(Personnel, body.personnel_id)
        if not person:
            raise HTTPException(status_code=404, detail="Personnel not found")
        sess = AgentSession(
            personnel_id=body.personnel_id,
            title=body.title,
        )
        session.add(sess)
        session.commit()
        session.refresh(sess)
        return _session_to_dict(sess, messages=[])


@router.get("/sessions/{session_id}")
def get_session_detail(session_id: str, _: User = Depends(get_current_user)):
    with get_session() as session:
        sess = session.get(AgentSession, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = session.exec(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
        ).all()
        return _session_to_dict(sess, list(messages))


@router.delete("/sessions/{session_id}", status_code=204)
async def close_session(session_id: str, background_tasks: BackgroundTasks,
                        _: User = Depends(get_current_user)):
    with get_session() as session:
        sess = session.get(AgentSession, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        sess.status = "closed"
        sess.updated_at = datetime.utcnow()
        session.add(sess)
        session.commit()
    background_tasks.add_task(generate_session_summary, session_id)


# ── Message streaming ─────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: MessageCreate,
                       _: User = Depends(get_current_user)):
    """Send a message to an agent and stream the response via SSE."""
    with get_session() as db:
        sess = db.get(AgentSession, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        if sess.status == "closed":
            raise HTTPException(status_code=409, detail="Session is closed")

    async def event_stream():
        stream_complete = False
        try:
            async for event in run_session(session_id, body.content):
                yield f"data: {json.dumps(event)}\n\n"
            stream_complete = True
            yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            if not stream_complete:
                # Client disconnected mid-stream — reset active session to idle
                with get_session() as db:
                    sess = db.get(AgentSession, session_id)
                    if sess and sess.status == "active":
                        sess.status = "idle"
                        sess.updated_at = datetime.utcnow()
                        db.add(sess)
                        db.commit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
