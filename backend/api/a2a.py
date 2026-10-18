"""
A2A (Agent-to-Agent) delegation API.

Flow:
  1. POST /a2a/requests        — requesting agent creates a delegation request
  2. POST /a2a/requests/{id}/approve     — responsible human of target agent approves the task
  3. Backend auto-executes target agent  — POST /sessions to run the task
  4. POST /a2a/requests/{id}/approve-result — responsible human approves the result
  5. Result returned to the originating session
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import select, update

from api.auth import get_current_user
from database import get_session
from models import (
    A2ARequest,
    AgentConfig,
    AgentSession,
    Personnel,
    SessionMessage,
    User,
)
from schemas import A2AApprove, A2AReject, A2ARequestCreate, A2AResultApprove
from services import authz

router = APIRouter(prefix="/a2a", tags=["a2a"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _req_to_dict(req: A2ARequest, session, *, show_result: bool = True) -> dict:
    from_agent = session.get(Personnel, req.from_agent_id)
    to_agent = session.get(Personnel, req.to_agent_id)
    approver = session.get(Personnel, req.approver_id) if req.approver_id else None

    return {
        "id": req.id,
        "from_session_id": req.from_session_id,
        "from_agent_id": req.from_agent_id,
        "from_agent_name": from_agent.name if from_agent else None,
        "to_agent_id": req.to_agent_id,
        "to_agent_name": to_agent.name if to_agent else None,
        "task": req.task,
        "context": req.context,
        "status": req.status,
        "result": req.result if show_result else None,
        "approver_id": req.approver_id,
        "approver_name": approver.name if approver else None,
        "approved_at": req.approved_at.isoformat() if req.approved_at else None,
        "result_approved_at": req.result_approved_at.isoformat()
        if req.result_approved_at
        else None,
        "rejection_reason": req.rejection_reason,
        "created_at": req.created_at.isoformat(),
        "updated_at": req.updated_at.isoformat(),
    }


def _auto_set_approver(req: A2ARequest, session) -> None:
    """Set approver_id to the responsible human of the target agent."""
    cfg = session.exec(
        select(AgentConfig).where(AgentConfig.personnel_id == req.to_agent_id)
    ).first()
    if cfg and cfg.responsible_id:
        req.approver_id = cfg.responsible_id


def _agent(session, pid: str) -> Personnel | None:
    return session.get(Personnel, pid)


def _can_see_req(session, user: User, req: A2ARequest) -> bool:
    """Both agents belong to one company the caller is in, and the caller manages
    one of them, is the designated approver, or started the originating session."""
    src = _agent(session, req.from_agent_id)
    dst = _agent(session, req.to_agent_id)
    if not src or not dst or src.company_id != dst.company_id:
        return False
    if not authz.is_member(session, user.id, dst.company_id):
        return False
    if req.approver_id:
        ap = session.get(Personnel, req.approver_id)
        if ap and ap.user_id == user.id:
            return True
    if req.from_session_id:
        sess = session.get(AgentSession, req.from_session_id)
        if sess and sess.user_id == user.id:
            return True
    return authz.can_manage_agent(session, user.id, src) or authz.can_manage_agent(
        session, user.id, dst
    )


def _may_decide(session, user: User, req: A2ARequest) -> bool:
    """Only the designated approver (the responsible human, matched to the
    authenticated user), or a company-wide founder/executive, decides a request."""
    dst = _agent(session, req.to_agent_id)
    if not dst or not authz.is_member(session, user.id, dst.company_id):
        return False
    if req.approver_id:
        ap = session.get(Personnel, req.approver_id)
        if ap and ap.user_id == user.id:
            return True
    elif authz.can_manage_agent(session, user.id, dst):
        return True
    return authz.has_role(
        session, user.id, dst.company_id, authz.FINAL, company_wide=True
    )


def _result_visible(session, user: User, req: A2ARequest) -> bool:
    """The result is released to the requesting side only once it is approved; until
    then only those who may decide on it can read it."""
    return req.status == "completed" or _may_decide(session, user, req)


def _own_request(session, user: User, req_id: str) -> A2ARequest:
    req = session.get(A2ARequest, req_id)
    if not req or not _can_see_req(session, user, req):
        raise HTTPException(status_code=404, detail="Request not found")
    return req


def _claim(session, req: A2ARequest, expected: tuple[str, ...], new: str) -> None:
    """Compare-and-swap the status; the loser of a race gets 409."""
    res = session.exec(
        update(A2ARequest)
        .where(A2ARequest.id == req.id, A2ARequest.status.in_(expected))
        .values(status=new)
    )
    if res.rowcount != 1:
        raise HTTPException(status_code=409, detail="Request already decided")


# ── CRUD ──────────────────────────────────────────────────────────────────────


@router.get("/requests")
def list_requests(
    company_id: str | None = None,
    approver_id: str | None = None,
    status: str | None = None,
    from_agent_id: str | None = None,
    to_agent_id: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        rows = _visible_requests(
            session, user, company_id, approver_id, status, from_agent_id, to_agent_id
        )
        return [
            _req_to_dict(r, session, show_result=_result_visible(session, user, r))
            for r in rows
        ]


def _visible_requests(
    session,
    user: User,
    company_id: str | None = None,
    approver_id: str | None = None,
    status: str | None = None,
    from_agent_id: str | None = None,
    to_agent_id: str | None = None,
) -> list[A2ARequest]:
    from sqlalchemy import or_

    q = select(A2ARequest).order_by(A2ARequest.created_at.desc())
    cids = [company_id] if company_id else authz.company_ids(session, user.id)
    if company_id:
        authz.require_member(session, user.id, company_id)
    agent_ids = list(
        session.exec(select(Personnel.id).where(Personnel.company_id.in_(cids))).all()
    )
    q = q.where(
        or_(
            A2ARequest.from_agent_id.in_(agent_ids),
            A2ARequest.to_agent_id.in_(agent_ids),
        )
    )
    if approver_id:
        q = q.where(A2ARequest.approver_id == approver_id)
    if status:
        q = q.where(A2ARequest.status == status)
    if from_agent_id:
        q = q.where(A2ARequest.from_agent_id == from_agent_id)
    if to_agent_id:
        q = q.where(A2ARequest.to_agent_id == to_agent_id)
    return [r for r in session.exec(q).all() if _can_see_req(session, user, r)]


@router.get("/requests/pending-count")
def pending_count(
    company_id: str | None = None, user: User = Depends(get_current_user)
):
    """Returns count of requests awaiting approval (for notification badge)."""
    with get_session() as session:
        rows = _visible_requests(session, user, company_id)
        return {
            "count": sum(
                1
                for r in rows
                if r.status in ("pending_approval", "pending_result_approval")
            )
        }


@router.post("/requests", status_code=201)
def create_request(body: A2ARequestCreate, user: User = Depends(get_current_user)):
    with get_session() as session:
        src = _agent(session, body.from_agent_id)
        dst = _agent(session, body.to_agent_id)
        if (
            not src
            or not dst
            or src.company_id != dst.company_id
            or not authz.is_member(session, user.id, src.company_id)
        ):
            raise HTTPException(status_code=404, detail="Personnel not found")
        sess = (
            session.get(AgentSession, body.from_session_id)
            if body.from_session_id
            else None
        )
        if body.from_session_id and (not sess or sess.personnel_id != src.id):
            raise HTTPException(status_code=404, detail="Session not found")
        # Delegating on behalf of an agent: its manager, or the owner of the chat
        # the delegation comes from.
        if not (
            authz.can_manage_agent(session, user.id, src)
            or (sess is not None and sess.user_id == user.id)
        ):
            raise HTTPException(
                status_code=403, detail="Bu ajan adına talep açamazsınız"
            )
        if not authz.agent_is_active(session, dst.id):
            raise HTTPException(status_code=409, detail="Hedef ajan etkin değil")

        req = A2ARequest(
            from_session_id=body.from_session_id,
            from_agent_id=body.from_agent_id,
            to_agent_id=body.to_agent_id,
            task=body.task,
            context=body.context,
            status="pending_approval",
        )
        _auto_set_approver(req, session)
        session.add(req)
        session.commit()
        session.refresh(req)
        return _req_to_dict(req, session)


@router.get("/requests/{req_id}")
def get_request(req_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        req = _own_request(session, user, req_id)
        return _req_to_dict(
            req, session, show_result=_result_visible(session, user, req)
        )


@router.post("/requests/{req_id}/approve")
def approve_request(
    req_id: str,
    body: A2AApprove,
    background_tasks: BackgroundTasks,
    caller: User = Depends(get_current_user),
):
    """Approve the task. Triggers execution in background."""
    with get_session() as session:
        req = _own_request(session, caller, req_id)
        if req.status != "pending_approval":
            raise HTTPException(
                status_code=409,
                detail=f"Request is not pending approval (status: {req.status})",
            )
        # The approver is the authenticated user, never a caller-supplied id.
        if not _may_decide(session, caller, req):
            raise HTTPException(
                status_code=403,
                detail="Yetkisiz: bu talebi onaylayacak kişi siz değilsiniz",
            )
        if not authz.agent_is_active(session, req.to_agent_id):
            raise HTTPException(status_code=409, detail="Hedef ajan etkin değil")
        _claim(session, req, ("pending_approval",), "running")
        mine = session.exec(
            select(Personnel).where(
                Personnel.user_id == caller.id,
                Personnel.company_id == _agent(session, req.to_agent_id).company_id,
            )
        ).first()
        req.status = "running"
        if mine:
            req.approver_id = mine.id
        req.approved_at = datetime.utcnow()
        req.updated_at = datetime.utcnow()
        session.add(req)
        session.commit()
        req_id_copy = req.id

    background_tasks.add_task(_execute_a2a_task, req_id_copy)
    return {"status": "running", "req_id": req_id_copy}


@router.post("/requests/{req_id}/approve-result")
def approve_result(
    req_id: str,
    body: A2AResultApprove,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Approve the result and mark the request as completed."""
    with get_session() as session:
        req = _own_request(session, user, req_id)
        if req.status != "pending_result_approval":
            raise HTTPException(
                status_code=409,
                detail=f"Request is not pending result approval (status: {req.status})",
            )
        if not _may_decide(session, user, req):
            raise HTTPException(status_code=403, detail="Yetkisiz")
        _claim(session, req, ("pending_result_approval",), "completed")
        req.status = "completed"
        req.result_approved_at = datetime.utcnow()
        req.updated_at = datetime.utcnow()
        session.add(req)
        session.commit()
        session.refresh(req)
        if req.from_session_id:
            background_tasks.add_task(_maybe_compile_results, req.from_session_id)
        return _req_to_dict(req, session)


@router.post("/requests/{req_id}/reject")
def reject_request(
    req_id: str,
    body: A2AReject,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        req = _own_request(session, user, req_id)
        if req.status not in ("pending_approval", "pending_result_approval"):
            raise HTTPException(
                status_code=409, detail="Request cannot be rejected at this stage"
            )
        if not _may_decide(session, user, req):
            raise HTTPException(status_code=403, detail="Yetkisiz")
        _claim(
            session, req, ("pending_approval", "pending_result_approval"), "rejected"
        )
        req.status = "rejected"
        req.rejection_reason = body.reason
        mine = session.exec(
            select(Personnel).where(
                Personnel.user_id == user.id,
                Personnel.company_id == _agent(session, req.to_agent_id).company_id,
            )
        ).first()
        if mine:
            req.approver_id = mine.id
        req.updated_at = datetime.utcnow()
        session.add(req)
        session.commit()
        session.refresh(req)
        if req.from_session_id:
            background_tasks.add_task(_maybe_compile_results, req.from_session_id)
        return _req_to_dict(req, session)


# ── Background execution ──────────────────────────────────────────────────────

# Tracks sessions that already triggered compilation (prevents double-run)
_COMPILE_TRIGGERED: set[str] = set()


async def _run_agent_task(session_id: str, task: str) -> str:
    """Run the agent and collect the full text response."""
    from services.agent_runtime import run_session

    text_parts = []
    async for event in run_session(session_id, task):
        if event["type"] == "text":
            text_parts.append(event["content"])
    return "".join(text_parts)


def _maybe_compile_results(from_session_id: str) -> None:
    """
    When all A2A delegations from a session finish, feed results back to the
    originating Council Agent session and generate a compiled final report.
    """
    if from_session_id in _COMPILE_TRIGGERED:
        return

    with get_session() as session:
        reqs = session.exec(
            select(A2ARequest).where(A2ARequest.from_session_id == from_session_id)
        ).all()

        if not reqs:
            return

        # Any still in flight?
        blocking = [
            r
            for r in reqs
            if r.status in ("pending_approval", "running", "pending_result_approval")
        ]
        if blocking:
            return

        # Collect results
        done = []
        for r in reqs:
            agent = session.get(Personnel, r.to_agent_id)
            name = agent.name if agent else "Ajan"
            if r.status == "completed" and r.result:
                done.append((name, r.result, r.status))
            elif r.status == "rejected":
                # An unapproved or rejected result is never released to the chat.
                done.append((name, "_Sonuç onaylanmadı / reddedildi._", r.status))

        if not done:
            return

    _COMPILE_TRIGGERED.add(from_session_id)

    # Build a pre-formatted executive report and write it directly as an assistant
    # message — avoids routing through the orchestrator agent which would re-delegate.
    parts = [
        f"### {'✅' if status == 'completed' else '❌'} {name}\n\n{result}"
        for name, result, status in done
    ]

    report = (
        "## 📊 Delegasyon Sonuçları — Yönetici Raporu\n\n"
        f"*{len(done)} ajan tamamlandı*\n\n" + "\n\n---\n\n".join(parts) + "\n\n---\n\n"
        "_Tüm delegasyon görevleri tamamlandı. Yukarıdaki raporları inceleyebilir, "
        "detayları sormak için mesaj yazabilirsiniz._"
    )

    try:
        with get_session() as session:
            msg = SessionMessage(
                session_id=from_session_id,
                role="assistant",
                content=report,
            )
            session.add(msg)
            session.commit()
    except Exception as e:
        import traceback

        print(f"[A2A Compile] {e}\n{traceback.format_exc()}")


def _execute_a2a_task(req_id: str) -> None:
    """
    Background task: create a temporary session for the target agent,
    run the task, auto-complete the request, then trigger compilation
    if all sibling delegations from the same session are done.
    """
    from_session_id_copy: str | None = None

    with get_session() as session:
        req = session.get(A2ARequest, req_id)
        if not req or req.status != "running":
            return

        from_session_id_copy = req.from_session_id

        ephemeral = AgentSession(
            personnel_id=req.to_agent_id,
            title=f"A2A: {req.task[:60]}",
        )
        session.add(ephemeral)
        session.commit()
        session.refresh(ephemeral)
        ephemeral_id = ephemeral.id

    full_task = req.task
    if req.context:
        full_task = f"{req.task}\n\nBağlam:\n{req.context}"

    try:
        result = asyncio.run(_run_agent_task(ephemeral_id, full_task))
    except Exception as e:
        result = f"[Görev yürütme hatası: {e}]"

    with get_session() as session:
        req = session.get(A2ARequest, req_id)
        if req:
            req.result = result or "[Boş yanıt]"
            # The result waits for the responsible human; nothing is released to the
            # originating chat before POST .../approve-result.
            req.status = "pending_result_approval"
            req.updated_at = datetime.utcnow()
            session.add(req)
            session.commit()


# ── Delegation status for chat UI ─────────────────────────────────────────────


@router.get("/sessions/{session_id}/delegation-status")
def session_delegation_status(session_id: str, user: User = Depends(get_current_user)):
    """Return counts of A2A requests originating from a session."""
    with get_session() as session:
        sess = session.get(AgentSession, session_id)
        person = session.get(Personnel, sess.personnel_id) if sess else None
        if (
            not sess
            or not person
            or not authz.is_member(session, user.id, person.company_id)
            or not (
                sess.user_id == user.id
                or authz.can_manage_agent(session, user.id, person)
            )
        ):
            raise HTTPException(status_code=404, detail="Session not found")
        reqs = session.exec(
            select(A2ARequest).where(A2ARequest.from_session_id == session_id)
        ).all()

    total = len(reqs)
    pending = sum(
        1
        for r in reqs
        if r.status in ("pending_approval", "running", "pending_result_approval")
    )
    completed = sum(1 for r in reqs if r.status == "completed")
    rejected = sum(1 for r in reqs if r.status == "rejected")
    return {
        "total": total,
        "pending": pending,
        "completed": completed,
        "rejected": rejected,
        "all_done": total > 0 and pending == 0,
    }
