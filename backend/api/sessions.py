import asyncio
import base64
import io
import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import AgentMemory, AgentSession, Personnel, SessionMessage, User
from schemas import Attachment, MessageCreate, SessionCreate
from services.agent_runtime import run_session
from services.memory_service import generate_session_summary

router = APIRouter(tags=["sessions"])

# Per-session asyncio queues for background task → SSE communication.
# Background task keeps running after client disconnects; queue is removed on disconnect.
_session_queues: dict[str, "asyncio.Queue[dict | None]"] = {}


def _session_to_dict(
    s: AgentSession, messages: list[SessionMessage] | None = None
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
def list_sessions(
    personnel_id: str | None = None,
    status: str | None = None,
    _: User = Depends(get_current_user),
):
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


# ── Memory ───────────────────────────────────────────────────────────────────


@router.get("/sessions/memories")
def list_memories(personnel_id: str | None = None, _: User = Depends(get_current_user)):
    with get_session() as session:
        q = select(AgentMemory).order_by(AgentMemory.created_at.desc())
        if personnel_id:
            q = q.where(AgentMemory.personnel_id == personnel_id)
        rows = session.exec(q).all()
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
async def close_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    _: User = Depends(get_current_user),
):
    with get_session() as session:
        sess = session.get(AgentSession, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        sess.status = "closed"
        sess.updated_at = datetime.utcnow()
        session.add(sess)
        session.commit()
    background_tasks.add_task(generate_session_summary, session_id)


# ── Status polling (for reconnect after navigation away) ─────────────────────


@router.get("/sessions/{session_id}/status")
def get_session_status(session_id: str, _: User = Depends(get_current_user)):
    """Returns current session status and all messages. Used for polling when reconnecting."""
    with get_session() as session:
        sess = session.get(AgentSession, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = session.exec(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
        ).all()
    return {
        "status": sess.status,
        "is_running": sess.status == "running",
        "messages": [_message_to_dict(m) for m in messages],
    }


# ── File upload ───────────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/files")
async def upload_file(
    session_id: str, file: UploadFile = File(...), _: User = Depends(get_current_user)
):
    """Upload a file (PDF or image) to be included in the next message."""
    with get_session() as db:
        sess = db.get(AgentSession, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
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
    session_id: str, body: MessageCreate, _: User = Depends(get_current_user)
):
    """
    Send a message and stream the response via SSE.
    The agent runs in a background task — navigation away does not kill the run.
    Call GET /sessions/{id}/status to poll for completion after reconnecting.
    """
    with get_session() as db:
        sess = db.get(AgentSession, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        if sess.status == "closed":
            raise HTTPException(status_code=409, detail="Session is closed")
        if sess.status == "running":
            raise HTTPException(
                status_code=409,
                detail="Session already running — check /status to poll",
            )

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
