import asyncio
import base64
import io
import json
import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import AgentMemory, AgentSession, Personnel, SessionMessage, User
from schemas import Attachment, MessageCreate, SessionCreate
from services import authz
from services.agent_runtime import run_session
from services.memory_service import generate_session_summary

router = APIRouter(tags=["sessions"])

# Per-session asyncio queues for background task → SSE communication.
# Background task keeps running after client disconnects; queue is removed on disconnect.
_session_queues: dict[str, "asyncio.Queue[dict | None]"] = {}


def _session_to_dict(
    s: AgentSession,
    messages: list[SessionMessage] | None = None,
    status_only: bool = False,
) -> dict:
    d = {
        "id": s.id,
        "personnel_id": s.personnel_id,
        "title": s.title,
        "status": s.status,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }
    if messages is not None:
        d["messages"] = [_message_to_dict(m, status_only) for m in messages]
    return d


_STATUS_NAME = re.compile(r"[A-Za-z][A-Za-z0-9._:/-]{0,47}")


def _status_name(value) -> str:
    return value if isinstance(value, str) and _STATUS_NAME.fullmatch(value) else "tool"


def _result_ok(result) -> bool:
    return (
        not str(result or "").lstrip().lower().startswith(("[error", "error", "hata"))
    )


def project_event(event: dict) -> dict | None:
    """The department view's stream: user-facing status events, never raw reasoning,
    tool arguments or tool results (ADR-0022 §7). Unknown event types are dropped."""
    t = event.get("type")
    if t == "text":
        return {"type": "text", "content": str(event.get("content", ""))}
    if t == "stream_end":
        return {"type": "stream_end"}
    if t == "sources":
        items = event.get("items")
        return {
            "type": "sources",
            "items": [
                {
                    "kind": str(i.get("kind", ""))[:40],
                    "date": str(i.get("date", ""))[:10],
                    "snippet": str(i.get("snippet", ""))[:160],
                }
                for i in (items if isinstance(items, list) else [])[:8]
                if isinstance(i, dict)
            ],
        }
    if t == "done":
        return {"type": "done", "message_id": event.get("message_id")}
    if t == "error":
        return {"type": "error", "message": "Bir hata oluştu"}
    if t == "tool_call":
        return {
            "type": "status",
            "step": "tool",
            "name": _status_name(event.get("name")),
        }
    if t == "tool_result":
        return {
            "type": "status",
            "step": "tool_done",
            "name": _status_name(event.get("name")),
            "ok": _result_ok(event.get("result")),
        }
    return None


def _message_to_dict(m: SessionMessage, status_only: bool = False) -> dict:
    calls = json.loads(m.tool_calls_json) if m.tool_calls_json else []
    results = json.loads(m.tool_results_json) if m.tool_results_json else []
    if status_only:
        calls = [
            {"name": _status_name(c.get("name"))} for c in calls if isinstance(c, dict)
        ]
        results = [
            {"name": _status_name(r.get("name")), "ok": _result_ok(r.get("result"))}
            for r in results
            if isinstance(r, dict)
        ]
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "tool_calls": calls,
        "tool_results": results,
        "tokens_used": m.tokens_used,
        "created_at": m.created_at.isoformat(),
    }


def _status_only(db, user: User, sess: AgentSession) -> bool:
    """The department view always gets status events, whatever it asks for."""
    person = db.get(Personnel, sess.personnel_id)
    return bool(person and authz.is_assistant_only(db, user.id, person.company_id))


# ── Session CRUD ──────────────────────────────────────────────────────────────


def _agent_for(db, user: User, personnel_id: str) -> Personnel:
    """The agent, 404 unless it belongs to one of the caller's companies."""
    person = db.get(Personnel, personnel_id)
    if not person or not authz.is_member(db, user.id, person.company_id):
        raise HTTPException(status_code=404, detail="Personnel not found")
    return person


def _can_see(
    db, user: User, sess: AgentSession, person: Personnel | None = None
) -> bool:
    """The session's owner, or anyone who manages the agent."""
    person = person or db.get(Personnel, sess.personnel_id)
    if sess.user_id == user.id:
        # The owner keeps access only while still in the company.
        return bool(person and authz.is_member(db, user.id, person.company_id))
    return bool(
        person
        and authz.is_member(db, user.id, person.company_id)
        and authz.can_manage_agent(db, user.id, person)
    )


def _own_session(db, user: User, session_id: str) -> AgentSession:
    sess = db.get(AgentSession, session_id)
    if not sess or not _can_see(db, user, sess):
        raise HTTPException(status_code=404, detail="Session not found")
    return sess


@router.get("/sessions")
def list_sessions(
    personnel_id: str | None = None,
    status: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        q = select(AgentSession).order_by(AgentSession.updated_at.desc())
        if personnel_id:
            _agent_for(session, user, personnel_id)
            q = q.where(AgentSession.personnel_id == personnel_id)
        if status:
            q = q.where(AgentSession.status == status)
        people: dict[str, Personnel | None] = {}
        rows = []
        for s in session.exec(q).all():
            if s.personnel_id not in people:
                people[s.personnel_id] = session.get(Personnel, s.personnel_id)
            if _can_see(session, user, s, people[s.personnel_id]):
                rows.append(s)

        result = []
        for s in rows:
            last_msg = session.exec(
                select(SessionMessage)
                .where(SessionMessage.session_id == s.id)
                .order_by(SessionMessage.created_at.desc())
            ).first()
            d = _session_to_dict(s)
            d["last_message"] = (
                _message_to_dict(last_msg, _status_only(session, user, s))
                if last_msg
                else None
            )
            result.append(d)
        return result


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate, user: User = Depends(get_current_user)):
    with get_session() as session:
        person = _agent_for(session, user, body.personnel_id)
        if authz.is_assistant_only(
            session, user.id, person.company_id
        ) and not authz.is_my_agent(session, user.id, person):
            # the department view chats with the person's own agent only
            raise HTTPException(status_code=404, detail="Personnel not found")
        if not authz.agent_is_active(session, body.personnel_id):
            raise HTTPException(status_code=409, detail="Ajan etkin değil")
        sess = AgentSession(
            personnel_id=body.personnel_id,
            user_id=user.id,
            title=body.title,
        )
        session.add(sess)
        session.commit()
        session.refresh(sess)
        return _session_to_dict(sess, messages=[])


# ── Memory ───────────────────────────────────────────────────────────────────


@router.get("/sessions/memories")
def list_memories(
    personnel_id: str | None = None, user: User = Depends(get_current_user)
):
    with get_session() as session:
        q = select(AgentMemory).order_by(AgentMemory.created_at.desc())
        if personnel_id:
            _agent_for(session, user, personnel_id)
            q = q.where(AgentMemory.personnel_id == personnel_id)
        # Memories summarise many people's chats: only the agent's managers read them.
        allowed: dict[str, bool] = {}
        rows = []
        for m in session.exec(q).all():
            if m.personnel_id not in allowed:
                person = session.get(Personnel, m.personnel_id)
                allowed[m.personnel_id] = bool(
                    person
                    and authz.is_member(session, user.id, person.company_id)
                    and authz.can_manage_agent(session, user.id, person)
                )
            if allowed[m.personnel_id]:
                rows.append(m)
        return [
            {
                "id": m.id,
                "personnel_id": m.personnel_id,
                "session_id": m.session_id,
                "summary": m.summary,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]


@router.get("/sessions/{session_id}")
def get_session_detail(session_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        sess = _own_session(session, user, session_id)
        messages = session.exec(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
        ).all()
        return _session_to_dict(sess, list(messages), _status_only(session, user, sess))


@router.delete("/sessions/{session_id}", status_code=204)
async def close_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        sess = _own_session(session, user, session_id)
        sess.status = "closed"
        sess.updated_at = datetime.utcnow()
        session.add(sess)
        session.commit()
    background_tasks.add_task(generate_session_summary, session_id)


# ── Status polling (for reconnect after navigation away) ─────────────────────


@router.get("/sessions/{session_id}/status")
def get_session_status(session_id: str, user: User = Depends(get_current_user)):
    """Returns current session status and all messages. Used for polling when reconnecting."""
    with get_session() as session:
        sess = _own_session(session, user, session_id)
        messages = session.exec(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
        ).all()
        status_only = _status_only(session, user, sess)
    return {
        "status": sess.status,
        "is_running": sess.status == "running",
        "messages": [_message_to_dict(m, status_only) for m in messages],
    }


# ── File upload ───────────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/files")
async def upload_file(
    session_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Upload a file (PDF or image) to be included in the next message."""
    with get_session() as db:
        sess = _own_session(db, user, session_id)
        if sess.status == "closed":
            raise HTTPException(status_code=409, detail="Session is closed")

    content_bytes = await file.read()
    filename = file.filename or "file"
    content_type = file.content_type or ""

    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        text = _extract_pdf_text(content_bytes)
        return {
            "type": "pdf",
            "filename": filename,
            "content": text,
            "mime_type": "application/pdf",
        }

    elif content_type.startswith("image/"):
        b64 = base64.b64encode(content_bytes).decode()
        data_uri = f"data:{content_type};base64,{b64}"
        return {
            "type": "image",
            "filename": filename,
            "content": data_uri,
            "mime_type": content_type,
        }

    else:
        # Try to read as plain text
        try:
            text = content_bytes.decode("utf-8")
            return {
                "type": "text",
                "filename": filename,
                "content": text,
                "mime_type": "text/plain",
            }
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Desteklenmeyen dosya formatı. PDF veya görsel yükleyin.",
            )


def _extract_pdf_text(content: bytes) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                parts.append(text.strip())
        return "\n\n".join(parts) if parts else "[PDF boş veya metin içermiyor]"
    except Exception as e:
        return f"[PDF okunamadı: {e}]"


# ── Background task runner ────────────────────────────────────────────────────


async def _run_background(
    session_id: str,
    content: str,
    queue: "asyncio.Queue[dict | None]",
    attachments: list[Attachment] | None,
):
    """
    Runs the agent in the background. Feeds events to `queue` while the SSE
    client is connected. Always saves to DB regardless of client state.
    """
    try:
        with get_session() as db:
            sess = db.get(AgentSession, session_id)
            if sess:
                sess.status = "running"
                sess.updated_at = datetime.utcnow()
                db.add(sess)
                db.commit()

        att_dicts = [a.model_dump() for a in attachments] if attachments else None

        async for event in run_session(session_id, content, attachments=att_dicts):
            # Only send to queue if this queue is still the active one for this session
            if _session_queues.get(session_id) is queue:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass  # Client not consuming fast enough; skip live update, DB has it

        # Signal done to SSE consumer
        if _session_queues.get(session_id) is queue:
            queue.put_nowait(None)

    except Exception as e:
        if _session_queues.get(session_id) is queue:
            try:
                queue.put_nowait({"type": "error", "message": str(e)})
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
    finally:
        with get_session() as db:
            sess = db.get(AgentSession, session_id)
            if sess and sess.status == "running":
                sess.status = "idle"
                sess.updated_at = datetime.utcnow()
                db.add(sess)
                db.commit()
        _session_queues.pop(session_id, None)


# ── Message streaming ─────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str, body: MessageCreate, user: User = Depends(get_current_user)
):
    """
    Send a message and stream the response via SSE.
    The agent runs in a background task — navigation away does not kill the run.
    Call GET /sessions/{id}/status to poll for completion after reconnecting.
    """
    with get_session() as db:
        sess = _own_session(db, user, session_id)
        if sess.status == "closed":
            raise HTTPException(status_code=409, detail="Session is closed")
        if not authz.agent_is_active(db, sess.personnel_id):
            raise HTTPException(status_code=409, detail="Ajan etkin değil")
        if sess.status == "running":
            raise HTTPException(
                status_code=409,
                detail="Session already running — check /status to poll",
            )
        status_only = _status_only(db, user, sess)

    queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=512)
    _session_queues[session_id] = queue

    asyncio.create_task(
        _run_background(session_id, body.content, queue, body.attachments)
    )

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300.0)
                except TimeoutError:
                    yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
                    return
                if event is None:
                    yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
                    return
                if status_only:
                    event = project_event(event)
                    if event is None:
                        continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            # Client disconnected — remove queue; background task continues
            _session_queues.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
