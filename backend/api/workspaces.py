"""Workspace lifecycle API (ADR-0018 §3).

Not implemented yet (ADR-0018 follow-ups): the WebSocket attach endpoint and its
single-use ticket, and the production runtime (workspace-controller client).
"""

import hashlib
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from api.audit import log_action
from api.auth import get_current_user
from database import get_session
from models import CompanyMember, User, Workspace
from services.workspace_runtime import (
    FileNotFound,
    WorkspaceRuntime,
    WorkspaceRuntimeError,
    WorkspaceSpec,
    get_runtime,
)
from services.workspaces import (
    MANAGER_ROLES,
    RETENTION,
    STALE_CREATING,
    can_manage,
    is_owner,
    live_workspace,
    person_for_user,
    safe_relpath,
    to_dict,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _mb(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default)) * 1024 * 1024
    except ValueError:
        return default * 1024 * 1024


def _audit(session, ws: Workspace, user: User, action: str, **details) -> None:
    log_action(
        session,
        action,
        "workspace",
        entity_id=ws.id,
        entity_name=ws.personnel_id,
        company_id=ws.company_id,
        user_id=user.id,
        details={"state": ws.state, "personnel_id": ws.personnel_id, **details},
    )


def _get(session, workspace_id: str) -> Workspace:
    ws = session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _touch(ws: Workspace, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    ws.updated_at = now
    ws.last_active_at = now


def _runtime_failed(ws: Workspace, session, e: Exception, *, mark: bool) -> None:
    if mark:
        ws.state = "failed"
        ws.error = str(e)[:500]
        ws.updated_at = datetime.utcnow()
        session.add(ws)
        session.commit()
    raise HTTPException(status_code=502, detail=f"Workspace runtime error: {e}")


# ── lifecycle ─────────────────────────────────────────────────────────────────


@router.post("", status_code=201)
def create_workspace(
    response: Response,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
    runtime: WorkspaceRuntime = Depends(get_runtime),
):
    """Create the caller's workspace. Idempotent: returns the live one if any."""
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        ws = live_workspace(session, person.id)
        now = datetime.utcnow()

        if ws is not None:
            stale = ws.state == "creating" and now - ws.updated_at > STALE_CREATING
            if ws.state in ("running", "suspended", "creating") and not stale:
                response.status_code = 200
                return to_dict(ws)
            # failed, or a creation that died half-way: retry (runtime.create is idempotent)
            ws.state = "creating"
            ws.error = None
        else:
            ws = Workspace(company_id=cid, personnel_id=person.id, user_id=user.id)
        ws.updated_at = now
        session.add(ws)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = live_workspace(session, person.id)
            if existing is None:
                raise
            response.status_code = 200
            return to_dict(existing)

        try:
            runtime.create(
                WorkspaceSpec(
                    workspace_id=ws.id, company_id=cid, personnel_id=person.id
                )
            )
        except WorkspaceRuntimeError as e:
            _runtime_failed(ws, session, e, mark=True)

        ws.state = "running"
        _touch(ws)
        session.add(ws)
        _audit(session, ws, user, "workspace_create")
        session.commit()
        return to_dict(ws)


@router.get("/me")
def my_workspace(user: User = Depends(get_current_user), company_id: str | None = None):
    with get_session() as session:
        person, _ = person_for_user(session, user, company_id)
        ws = live_workspace(session, person.id)
        if not ws:
            raise HTTPException(status_code=404, detail="No workspace yet")
        return to_dict(ws)


@router.get("")
def list_workspaces(
    company_id: str | None = None,
    include_deleted: bool = False,
    user: User = Depends(get_current_user),
):
    """Managers: workspaces they may manage (company / department scope)."""
    with get_session() as session:
        member_q = select(CompanyMember).where(
            CompanyMember.user_id == user.id,
            CompanyMember.role.in_(MANAGER_ROLES),
        )
        if company_id:
            member_q = member_q.where(CompanyMember.company_id == company_id)
        company_ids = {m.company_id for m in session.exec(member_q).all()}
        if not company_ids:
            raise HTTPException(status_code=403, detail="Manager role required")
        q = select(Workspace).where(Workspace.company_id.in_(company_ids))
        if not include_deleted:
            q = q.where(Workspace.state != "deleted")
        rows = session.exec(q.order_by(Workspace.created_at)).all()
        return [to_dict(w) for w in rows if can_manage(session, user, w)]


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        ws = _get(session, workspace_id)
        if not (is_owner(ws, user) or can_manage(session, user, ws)):
            raise HTTPException(status_code=403, detail="Not allowed")
        return to_dict(ws)


@router.post("/{workspace_id}/suspend")
def suspend_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    runtime: WorkspaceRuntime = Depends(get_runtime),
):
    with get_session() as session:
        ws = _get(session, workspace_id)
        if not (is_owner(ws, user) or can_manage(session, user, ws)):
            raise HTTPException(status_code=403, detail="Not allowed")
        if ws.state == "suspended":
            return to_dict(ws)
        if ws.state != "running":
            raise HTTPException(
                status_code=409, detail=f"Cannot suspend a {ws.state} workspace"
            )
        try:
            runtime.stop(ws.id)
        except WorkspaceRuntimeError as e:
            _runtime_failed(ws, session, e, mark=False)
        ws.state = "suspended"
        ws.suspended_at = datetime.utcnow()
        ws.updated_at = ws.suspended_at
        session.add(ws)
        _audit(session, ws, user, "workspace_suspend")
        session.commit()
        return to_dict(ws)


@router.post("/{workspace_id}/resume")
def resume_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    runtime: WorkspaceRuntime = Depends(get_runtime),
):
    with get_session() as session:
        ws = _get(session, workspace_id)
        if not is_owner(ws, user):
            raise HTTPException(status_code=403, detail="Only the owner can resume")
        if ws.state == "running":
            return to_dict(ws)
        if ws.state != "suspended":
            raise HTTPException(
                status_code=409, detail=f"Cannot resume a {ws.state} workspace"
            )
        try:
            runtime.start(ws.id)
        except WorkspaceRuntimeError as e:
            _runtime_failed(ws, session, e, mark=False)
        ws.state = "running"
        ws.suspended_at = None
        _touch(ws)
        session.add(ws)
        _audit(session, ws, user, "workspace_resume")
        session.commit()
        return to_dict(ws)


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    runtime: WorkspaceRuntime = Depends(get_runtime),
):
    """Remove the container; the volume is kept for 7 days (restorable)."""
    with get_session() as session:
        ws = _get(session, workspace_id)
        if not (is_owner(ws, user) or can_manage(session, user, ws)):
            raise HTTPException(status_code=403, detail="Not allowed")
        if ws.state == "deleted":
            raise HTTPException(status_code=409, detail="Already deleted")
        try:
            runtime.remove(ws.id)
        except WorkspaceRuntimeError as e:
            _runtime_failed(ws, session, e, mark=False)
        now = datetime.utcnow()
        ws.state = "deleted"
        ws.deleted_at = now
        ws.purge_after = now + RETENTION
        ws.updated_at = now
        session.add(ws)
        _audit(
            session,
            ws,
            user,
            "workspace_delete",
            purge_after=ws.purge_after.isoformat(),
        )
        session.commit()
    return Response(status_code=204)


@router.post("/{workspace_id}/restore")
def restore_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    runtime: WorkspaceRuntime = Depends(get_runtime),
):
    """Manager-only: bring a deleted workspace back within the retention window."""
    with get_session() as session:
        ws = _get(session, workspace_id)
        if not can_manage(session, user, ws):
            raise HTTPException(status_code=403, detail="Manager role required")
        now = datetime.utcnow()
        if ws.state != "deleted" or ws.purge_after is None or ws.purge_after <= now:
            raise HTTPException(
                status_code=409, detail="Not restorable (not deleted or past retention)"
            )
        if live_workspace(session, ws.personnel_id) is not None:
            raise HTTPException(
                status_code=409, detail="The person already has a live workspace"
            )
        try:
            runtime.restore(ws.id)
        except WorkspaceRuntimeError as e:
            _runtime_failed(ws, session, e, mark=False)
        ws.state = "running"
        ws.deleted_at = None
        ws.purge_after = None
        _touch(ws, now)
        session.add(ws)
        try:
            _audit(session, ws, user, "workspace_restore")
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="The person already has a live workspace"
            )
        return to_dict(ws)


# ── files (owner only: a manager can manage a workspace, not read its documents) ──


def _files_workspace(session, workspace_id: str, user: User) -> Workspace:
    ws = _get(session, workspace_id)
    if not is_owner(ws, user):
        raise HTTPException(status_code=403, detail="Only the owner can access files")
    if ws.state not in ("running", "suspended"):
        raise HTTPException(
            status_code=409, detail=f"Files unavailable for a {ws.state} workspace"
        )
    return ws


@router.get("/{workspace_id}/files")
def list_files(
    workspace_id: str,
    since: int = 0,
    user: User = Depends(get_current_user),
    runtime: WorkspaceRuntime = Depends(get_runtime),
):
    """Manifest of `out/`. `since` is the `cursor` of a previous response.

    v1 reports additions and changes only (outputs are versioned by name and never
    deleted by the agent — ADR-0019 §8); deletions are not propagated.
    """
    with get_session() as session:
        ws = _files_workspace(session, workspace_id, user)
        try:
            infos = runtime.list_files(ws.id, "out")
        except WorkspaceRuntimeError as e:
            raise HTTPException(status_code=502, detail=f"Workspace runtime error: {e}")
    fresh = [f for f in infos if f.mtime_ns > since]
    return {
        "files": [
            {
                "path": f.path.removeprefix("out/"),
                "size": f.size,
                "sha256": f.sha256,
                "mtime_ns": f.mtime_ns,
            }
            for f in fresh
        ],
        "cursor": max([since] + [f.mtime_ns for f in fresh]),
    }


@router.get("/{workspace_id}/files/{path:path}")
def download_file(
    workspace_id: str,
    path: str,
    user: User = Depends(get_current_user),
    runtime: WorkspaceRuntime = Depends(get_runtime),
):
    rel = safe_relpath(path)
    with get_session() as session:
        ws = _files_workspace(session, workspace_id, user)
        try:
            data = runtime.read_file(ws.id, f"out/{rel}")
        except FileNotFound:
            raise HTTPException(status_code=404, detail="File not found")
        except WorkspaceRuntimeError as e:
            raise HTTPException(status_code=502, detail=f"Workspace runtime error: {e}")
        if len(data) > _mb("WORKSPACE_MAX_DOWNLOAD_MB", 200):
            raise HTTPException(status_code=413, detail="File too large")
        _audit(session, ws, user, "workspace_file_download", path=rel, size=len(data))
        session.commit()
    name = rel.rsplit("/", 1)[-1].replace('"', "")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.put("/{workspace_id}/files/{path:path}", status_code=201)
async def upload_file(
    workspace_id: str,
    path: str,
    request: Request,
    user: User = Depends(get_current_user),
    runtime: WorkspaceRuntime = Depends(get_runtime),
):
    """Upload the raw request body to `in/<path>` (size-capped)."""
    rel = safe_relpath(path)
    cap = _mb("WORKSPACE_MAX_UPLOAD_MB", 50)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        raise HTTPException(status_code=413, detail="File too large")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            raise HTTPException(status_code=413, detail="File too large")
        chunks.append(chunk)
    data = b"".join(chunks)

    with get_session() as session:
        ws = _files_workspace(session, workspace_id, user)
        try:
            runtime.write_file(ws.id, f"in/{rel}", data)
        except WorkspaceRuntimeError as e:
            raise HTTPException(status_code=502, detail=f"Workspace runtime error: {e}")
        if ws.state == "running":
            _touch(ws)
            session.add(ws)
        _audit(session, ws, user, "workspace_file_upload", path=rel, size=size)
        session.commit()
    return {"path": rel, "size": size, "sha256": hashlib.sha256(data).hexdigest()}
